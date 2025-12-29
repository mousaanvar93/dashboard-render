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

SUCCESSFN_POLL_SECONDS = 15          # ✅ SuccessFN every 15s
SHAREPOINT_POLL_SECONDS = 300        # ✅ SharePoint every 5 minutes
XRATES_POLL_SECONDS = 300            # ✅ XRATES every 5 minutes

# --------------------------
# YOUR MATH
# --------------------------
DIVISOR = 31.1035
MULT_A = 3.674
MULT_B = 0.916

ITEMS = {
    "TL": {"id": 1, "use_0916": True,  "tag": "22EXCH", "color": "#FFD700"},
    "BL": {"id": 2, "use_0916": False, "tag": "24EXCH", "color": "#FFD700"},
    "TR": {"id": 3, "use_0916": True,  "tag": "22CASH", "color": "#00FF66"},
    "BR": {"id": 4, "use_0916": False, "tag": "24CASH", "color": "#00FF66"},
}

# --------------------------
# GRAPH / SHAREPOINT CONFIG (Render env vars)
# --------------------------
TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

SP_HOST = os.environ.get("SP_HOST", "anvarluxuryjewellery.sharepoint.com")
SP_SITE_PATH = os.environ.get("SP_SITE_PATH", "/sites/PRODUCTENTRY")

# list for the 4 IDs
SP_LIST_NAME = os.environ.get("SP_LIST_NAME", "staffinstructions")
SP_COLUMN_NAME = os.environ.get("SP_COLUMN_NAME", "setval")

# list for xrates (top 10)
XRATES_LIST_NAME = os.environ.get("XRATES_LIST_NAME", "xrates")
XRATES_RATE_FIELD = os.environ.get("XRATES_RATE_FIELD", "rate")
XRATES_TYPE_FIELD = os.environ.get("XRATES_TYPE_FIELD", "type")

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


def graph_get(url: str, timeout=25):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


# --------------------------
# HELPERS
# --------------------------
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

    # The API returns space-separated CSV records
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


# --------------------------
# SHAREPOINT
# --------------------------
_site_id_cache = None


def fetch_site_id():
    url = f"https://graph.microsoft.com/v1.0/sites/{SP_HOST}:{SP_SITE_PATH}"
    return graph_get(url)["id"]


def ensure_site_id():
    global _site_id_cache
    if not _site_id_cache:
        _site_id_cache = fetch_site_id()
    return _site_id_cache


def fetch_setval(site_id: str, item_id: int):
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        f"/lists/{SP_LIST_NAME}"
        f"/items/{item_id}?expand=fields"
    )
    data = graph_get(url)
    return data.get("fields", {}).get(SP_COLUMN_NAME, "")


def fetch_xrates_top10(site_id: str):
    # Order by ID ascending, take first 10
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        f"/lists/{XRATES_LIST_NAME}"
        f"/items?$top=10&$orderby=id asc&expand=fields"
    )
    data = graph_get(url)
    items = data.get("value", [])
    out = []
    for it in items:
        fields = it.get("fields", {}) or {}
        rate = fields.get(XRATES_RATE_FIELD)
        typ = fields.get(XRATES_TYPE_FIELD)

        # Keep as strings for display
        out.append({
            "rate": "" if rate is None else str(rate),
            "type": "" if typ is None else str(typ),
        })
    return out


# --------------------------
# FASTAPI
# --------------------------
app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


# --------------------------
# CACHES (two timers)
# --------------------------
_lock = threading.Lock()

_success_cache = {"value": None, "ts": 0.0}
_sharepoint_cache = {"vals": None, "ts": 0.0}
_xrates_cache = {"items": None, "ts": 0.0}


def get_success_value():
    now = time.time()
    if _success_cache["value"] is not None and (now - _success_cache["ts"]) < SUCCESSFN_POLL_SECONDS:
        return _success_cache["value"]

    val = fetch_successfn_price()
    _success_cache["value"] = val
    _success_cache["ts"] = now
    return val


def get_sharepoint_values(site_id: str):
    now = time.time()
    if _sharepoint_cache["vals"] is not None and (now - _sharepoint_cache["ts"]) < SHAREPOINT_POLL_SECONDS:
        return _sharepoint_cache["vals"]

    vals = {}
    for key, cfg in ITEMS.items():
        raw = fetch_setval(site_id, cfg["id"])
        vals[key] = raw

    _sharepoint_cache["vals"] = vals
    _sharepoint_cache["ts"] = now
    return vals


def get_xrates(site_id: str):
    now = time.time()
    if _xrates_cache["items"] is not None and (now - _xrates_cache["ts"]) < XRATES_POLL_SECONDS:
        return _xrates_cache["items"]

    items = fetch_xrates_top10(site_id)
    _xrates_cache["items"] = items
    _xrates_cache["ts"] = now
    return items


def blank_payload(status: str):
    return {
        "status": status,
        "TL": {"tag": ITEMS["TL"]["tag"], "value": "—"},
        "TR": {"tag": ITEMS["TR"]["tag"], "value": "—"},
        "BL": {"tag": ITEMS["BL"]["tag"], "value": "—"},
        "BR": {"tag": ITEMS["BR"]["tag"], "value": "—"},
    }


@app.get("/api/values")
def api_values():
    # returns the 4-squares values
    with _lock:
        try:
            site_id = ensure_site_id()
        except Exception:
            return JSONResponse(blank_payload("SHAREPOINT ERROR (SITE)"))

        try:
            success_val = get_success_value()
            if success_val is None:
                return JSONResponse(blank_payload("SUCCESSFN ERROR"))

            raw_map = get_sharepoint_values(site_id)

            out = {"status": "OK"}
            for key, cfg in ITEMS.items():
                sp_val = safe_float(raw_map.get(key))
                if sp_val is None:
                    out[key] = {"tag": cfg["tag"], "value": "INVALID"}
                    continue
                final = compute_final(success_val, sp_val, cfg["use_0916"])
                out[key] = {"tag": cfg["tag"], "value": f"{final:,.0f}"}
            return JSONResponse(out)

        except Exception:
            return JSONResponse(blank_payload("SHAREPOINT ERROR (LIST)"))


@app.get("/api/xrates")
def api_xrates():
    # returns top 10 list for tap-to-show screen
    with _lock:
        try:
            site_id = ensure_site_id()
        except Exception:
            return JSONResponse({"status": "SHAREPOINT ERROR (SITE)", "items": []})

        try:
            items = get_xrates(site_id)
            return JSONResponse({"status": "OK", "items": items})
        except Exception:
            return JSONResponse({"status": "SHAREPOINT ERROR (XRATES)", "items": []})
