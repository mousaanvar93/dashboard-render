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

# Gold (LLGUSD) used for 4 squares
SUCCESSFN_GOLD_SYMBOL = "LLGUSD"

# Silver (LLSUSD) used for new KILO SILVER boxes
SUCCESSFN_SILVER_SYMBOL = "LLSUSD"

SUCCESSFN_POLL_SECONDS = 15          # ✅ SuccessFN every 15s
SHAREPOINT_POLL_SECONDS = 300        # ✅ SharePoint every 5 minutes
XRATES_POLL_SECONDS = 300            # ✅ XRATES every 5 minutes

# --------------------------
# YOUR MATH (4 squares)
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
# SILVER BOXES CONFIG
# --------------------------
SILVER_BUY_ID = 5   # subtract this
SILVER_SELL_ID = 6  # add this
SILVER_MULT = 3.674
SILVER_TO_KILO = 32.15

# --------------------------
# GRAPH / SHAREPOINT CONFIG (Render env vars)
# --------------------------
TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

SP_HOST = os.environ.get("SP_HOST", "anvarluxuryjewellery.sharepoint.com")
SP_SITE_PATH = os.environ.get("SP_SITE_PATH", "/sites/PRODUCTENTRY")

# list for values (IDs 1..6)
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
        v = float(s)
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return v
    except Exception:
        return None


def parse_successfn_symbol(text: str, symbol: str):
    """
    SuccessFN endpoint returns space-separated CSV records, like:
    LLGUSD,4531.91,4531.91,...
    LLSUSD,79.055,79.055,...
    We need the first number after the symbol.
    """
    records = text.replace("\r", "\n").split()
    for rec in records:
        parts = [p.strip() for p in rec.split(",")]
        if len(parts) >= 2 and parts[0] == symbol:
            return safe_float(parts[1])
    return None


def fetch_successfn_prices():
    """
    Fetch once, parse both gold & silver from same payload.
    Returns: (gold_price, silver_price)
    """
    r = requests.get(SUCCESSFN_API_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    text = r.text.strip()
    gold = parse_successfn_symbol(text, SUCCESSFN_GOLD_SYMBOL)
    silver = parse_successfn_symbol(text, SUCCESSFN_SILVER_SYMBOL)
    return gold, silver


def compute_final_4squares(gold_val, sp_val, use_0916):
    base = (gold_val / DIVISOR) * MULT_A
    if use_0916:
        base *= MULT_B
    return base - sp_val


def compute_kilo_silver(silver_val: float, delta: float):
    """
    Final = ((silver_val + delta) * 3.674) * 32.15
    For BUY: delta = -ID5
    For SELL: delta = +ID6
    """
    return ((silver_val + delta) * SILVER_MULT) * SILVER_TO_KILO


# --------------------------
# SHAREPOINT (Graph)
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
# CACHES
# --------------------------
_lock = threading.Lock()

# Cache both gold & silver from successfn
_success_cache = {"gold": None, "silver": None, "ts": 0.0}

# Cache SharePoint item values (IDs 1..6)
_sharepoint_cache = {"vals": None, "ts": 0.0}

# Cache XRATES
_xrates_cache = {"items": None, "ts": 0.0}


def get_success_values():
    now = time.time()
    if _success_cache["gold"] is not None and (now - _success_cache["ts"]) < SUCCESSFN_POLL_SECONDS:
        return _success_cache["gold"], _success_cache["silver"]

    gold, silver = fetch_successfn_prices()
    _success_cache["gold"] = gold
    _success_cache["silver"] = silver
    _success_cache["ts"] = now
    return gold, silver


def get_sharepoint_values(site_id: str):
    now = time.time()
    if _sharepoint_cache["vals"] is not None and (now - _sharepoint_cache["ts"]) < SHAREPOINT_POLL_SECONDS:
        return _sharepoint_cache["vals"]

    vals = {}

    # IDs 1..4
    for key, cfg in ITEMS.items():
        vals[key] = fetch_setval(site_id, cfg["id"])

    # IDs 5..6 (silver)
    vals["SILVER_BUY_ID5"] = fetch_setval(site_id, SILVER_BUY_ID)
    vals["SILVER_SELL_ID6"] = fetch_setval(site_id, SILVER_SELL_ID)

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
        "silver_buy": "—",
        "silver_sell": "—",
    }


@app.get("/api/values")
def api_values():
    with _lock:
        try:
            site_id = ensure_site_id()
        except Exception:
            return JSONResponse(blank_payload("SHAREPOINT ERROR (SITE)"))

        try:
            gold_val, silver_val = get_success_values()
            if gold_val is None:
                return JSONResponse(blank_payload("SUCCESSFN ERROR (LLGUSD)"))
            if silver_val is None:
                payload = blank_payload("SUCCESSFN ERROR (LLSUSD)")
                payload["status"] = "SUCCESSFN ERROR (LLSUSD)"
                return JSONResponse(payload)

            raw_map = get_sharepoint_values(site_id)

            out = {"status": "OK"}

            # 4 squares
            for key, cfg in ITEMS.items():
                sp_val = safe_float(raw_map.get(key))
                if sp_val is None:
                    out[key] = {"tag": cfg["tag"], "value": "INVALID"}
                    continue
                final = compute_final_4squares(gold_val, sp_val, cfg["use_0916"])
                out[key] = {"tag": cfg["tag"], "value": f"{final:,.0f}"}

            # Silver squares
            # BUY: subtract ID 5
            # SELL: add ID 6
            id5 = safe_float(raw_map.get("SILVER_BUY_ID5"))
            id6 = safe_float(raw_map.get("SILVER_SELL_ID6"))

            if id5 is None:
                out["silver_buy"] = "INVALID"
            else:
                kb = compute_kilo_silver(silver_val, -id5)  # ✅ subtract
                out["silver_buy"] = f"{kb:,.0f}"

            if id6 is None:
                out["silver_sell"] = "INVALID"
            else:
                ks = compute_kilo_silver(silver_val, +id6)  # ✅ add
                out["silver_sell"] = f"{ks:,.0f}"

            return JSONResponse(out)

        except Exception:
            return JSONResponse(blank_payload("SHAREPOINT ERROR (LIST)"))


@app.get("/api/xrates")
def api_xrates():
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
