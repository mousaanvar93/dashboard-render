import os
import time
import threading
import requests
import msal

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# --------------------------
# SUCCESSFN
# --------------------------
SUCCESSFN_API_URL = "https://www.successfn.com/wp-content/themes/neve/page-templates/getprice.php?site=cfgs"
SUCCESSFN_SYMBOL = "LLGUSD"

# --------------------------
# YOUR MATH
# --------------------------
DIVISOR = 31.1035
MULT_A = 3.674
MULT_B = 0.916

ITEMS = {
    "TL": {"id": 1, "use_0916": True,  "tag": "22EXCH"},
    "BL": {"id": 2, "use_0916": False, "tag": "24EXCH"},
    "TR": {"id": 3, "use_0916": True,  "tag": "22CASH"},
    "BR": {"id": 4, "use_0916": False, "tag": "24CASH"},
}

POLL_SECONDS = 10

# --------------------------
# GRAPH / SHAREPOINT CONFIG (Render env vars)
# --------------------------
TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

SP_HOST = os.environ.get("SP_HOST", "anvarluxuryjewellery.sharepoint.com")
SP_SITE_PATH = os.environ.get("SP_SITE_PATH", "/sites/PRODUCTENTRY")
SP_LIST_NAME = os.environ.get("SP_LIST_NAME", "staffinstructions")
SP_COLUMN_NAME = os.environ.get("SP_COLUMN_NAME", "setval")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]

msal_app = msal.ConfidentialClientApplication(
    client_id=CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET,
)

_access_token = None
_token_expires_at = 0


def get_access_token() -> str:
    global _access_token, _token_expires_at
    now = int(time.time())
    if _access_token and now < (_token_expires_at - 60):
        return _access_token

    result = msal_app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"Token error: {result}")

    _access_token = result["access_token"]
    _token_expires_at = now + int(result.get("expires_in", 3600))
    return _access_token


def graph_get(url: str, timeout=20):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def safe_float(x):
    if x is None:
        return None
    s = str(x).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def fetch_successfn_price():
    r = requests.get(SUCCESSFN_API_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    text = r.text.strip()

    records = text.replace("\r", "\n").split()
    for rec in records:
        parts = [p.strip() for p in rec.split(",") if p.strip()]
        if len(parts) >= 2 and parts[0] == SUCCESSFN_SYMBOL:
            return safe_float(parts[1])
    return None


def compute_final(success_val, sp_val, use_0916):
    base = (success_val / DIVISOR) * MULT_A
    if use_0916:
        base *= MULT_B
    return base - sp_val


_site_id_cache = None


def fetch_site_id():
    url = f"https://graph.microsoft.com/v1.0/sites/{SP_HOST}:{SP_SITE_PATH}"
    return graph_get(url)["id"]


def fetch_setval(site_id: str, item_id: int):
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        f"/lists/{SP_LIST_NAME}"
        f"/items/{item_id}?expand=fields"
    )
    data = graph_get(url)
    return data.get("fields", {}).get(SP_COLUMN_NAME, "")


app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


_lock = threading.Lock()
_last_payload = None
_last_time = 0


def blank_payload(status: str):
    return {
        "status": status,
        "TL": {"tag": ITEMS["TL"]["tag"], "value": "—"},
        "TR": {"tag": ITEMS["TR"]["tag"], "value": "—"},
        "BL": {"tag": ITEMS["BL"]["tag"], "value": "—"},
        "BR": {"tag": ITEMS["BR"]["tag"], "value": "—"},
    }


def build_payload():
    global _site_id_cache

    try:
        success_val = fetch_successfn_price()
        if success_val is None:
            return blank_payload("SUCCESSFN ERROR")
    except Exception:
        return blank_payload("SUCCESSFN ERROR")

    try:
        if not _site_id_cache:
            _site_id_cache = fetch_site_id()
    except Exception:
        _site_id_cache = None
        return blank_payload("SHAREPOINT ERROR")

    out = {"status": "OK"}
    try:
        for key, cfg in ITEMS.items():
            raw = fetch_setval(_site_id_cache, cfg["id"])
            sp_val = safe_float(raw)
            if sp_val is None:
                out[key] = {"tag": cfg["tag"], "value": "INVALID SETVAL"}
                continue

            final = compute_final(success_val, sp_val, cfg["use_0916"])
            out[key] = {"tag": cfg["tag"], "value": f"{final:,.0f}"}
    except Exception:
        return blank_payload("SHAREPOINT ERROR")

    return out


@app.get("/api/values")
def api_values():
    global _last_payload, _last_time
    now = time.time()
    with _lock:
        if _last_payload is None or (now - _last_time) >= POLL_SECONDS:
            _last_payload = build_payload()
            _last_time = now
        return JSONResponse(_last_payload)
