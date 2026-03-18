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
SUCCESSFN_GOLD_SYMBOL = "LLGUSD"
SUCCESSFN_SILVER_SYMBOL = "LLSUSD"

SUCCESSFN_POLL_SECONDS = 15
SHAREPOINT_POLL_SECONDS = 300
XRATES_POLL_SECONDS = 300
DISCOUNTS_POLL_SECONDS = 300

# --------------------------
# YOUR MATH (4 squares)
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

# --------------------------
# SILVER
# --------------------------
SILVER_BUY_ID = 5
SILVER_SELL_ID = 6
SILVER_MULT = 3.674
SILVER_TO_KILO = 32.15

# --------------------------
# NEW SCREEN IDs
# --------------------------
DISCOUNT_22_ID = 37
DISCOUNT_24_ID = 38
SELL_PRICE_22_ID = 39
SELL_PRICE_24_ID = 40

# --------------------------
# DISCOUNTS SCREENS
# --------------------------
DISCOUNTS_SECTIONS = {
    "PAMP": (11, 21),
    "LOCAL": (22, 28),
    "VALCAMBI": (29, 36),
}

# --------------------------
# GRAPH CONFIG
# --------------------------
TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

SP_HOST = os.environ.get("SP_HOST", "anvarluxuryjewellery.sharepoint.com")
SP_SITE_PATH = os.environ.get("SP_SITE_PATH", "/sites/PRODUCTENTRY")

SP_LIST_NAME = os.environ.get("SP_LIST_NAME", "staffinstructions")
SP_COLUMN_NAME = os.environ.get("SP_COLUMN_NAME", "setval")
SP_CERTCHARGE_COLUMN = os.environ.get("SP_CERTCHARGE_COLUMN", "certcharge")

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


def get_access_token():
    global _access_token, _token_expires_at
    now = int(time.time())
    if _access_token and now < (_token_expires_at - 60):
        return _access_token

    result = msal_app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        raise RuntimeError(result)

    _access_token = result["access_token"]
    _token_expires_at = now + int(result.get("expires_in", 3600))
    return _access_token


def graph_get(url):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    return r.json()


# --------------------------
# HELPERS
# --------------------------
def safe_float(x):
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except:
        return None


def fmt0(x):
    if x is None:
        return "INVALID"
    return f"{x:,.0f}"


def fmt2(x):
    if x is None:
        return "INVALID"
    return f"{x:,.2f}"


def parse_successfn_symbol(text, symbol):
    for rec in text.split():
        parts = rec.split(",")
        if len(parts) >= 2 and parts[0] == symbol:
            return safe_float(parts[1])
    return None


def fetch_successfn_prices():
    r = requests.get(SUCCESSFN_API_URL, timeout=20)
    r.raise_for_status()
    txt = r.text.strip()
    return (
        parse_successfn_symbol(txt, SUCCESSFN_GOLD_SYMBOL),
        parse_successfn_symbol(txt, SUCCESSFN_SILVER_SYMBOL),
    )


def compute_final_4squares(gold_val, sp_val, use_0916):
    base = (gold_val / DIVISOR) * MULT_A
    if use_0916:
        base *= MULT_B
    return base - sp_val


def compute_kilo_silver(silver_val, delta):
    return ((silver_val + delta) * SILVER_MULT) * SILVER_TO_KILO


# --------------------------
# SHAREPOINT
# --------------------------
_site_id_cache = None


def ensure_site_id():
    global _site_id_cache
    if not _site_id_cache:
        url = f"https://graph.microsoft.com/v1.0/sites/{SP_HOST}:{SP_SITE_PATH}"
        _site_id_cache = graph_get(url)["id"]
    return _site_id_cache


def fetch_setval(site_id, item_id):
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{SP_LIST_NAME}/items/{item_id}?expand=fields"
    return graph_get(url)["fields"].get(SP_COLUMN_NAME)


def fetch_xrates(site_id):
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{XRATES_LIST_NAME}/items?$top=10&expand=fields"
    data = graph_get(url)
    return [
        {
            "rate": str(i["fields"].get(XRATES_RATE_FIELD, "")),
            "type": str(i["fields"].get(XRATES_TYPE_FIELD, "")),
        }
        for i in data.get("value", [])
    ]


def fetch_discounts_section(site_id, sec):
    if sec not in DISCOUNTS_SECTIONS:
        return []
    s, e = DISCOUNTS_SECTIONS[sec]
    rows = []
    for i in range(s, e + 1):
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{SP_LIST_NAME}/items/{i}?expand=fields"
        f = graph_get(url)["fields"]
        rows.append({
            "type": f.get("Title", ""),
            "disc": f.get(SP_COLUMN_NAME, ""),
            "cert_charge": f.get(SP_CERTCHARGE_COLUMN, ""),
        })
    return rows


# --------------------------
# FASTAPI
# --------------------------
app = FastAPI()
_lock = threading.Lock()


@app.get("/", response_class=HTMLResponse)
def home():
    return open("index.html", encoding="utf-8").read()


@app.get("/api/values")
def api_values():
    with _lock:
        try:
            site = ensure_site_id()
            gold, silver = fetch_successfn_prices()

            raw = {}

            for k, v in ITEMS.items():
                raw[k] = safe_float(fetch_setval(site, v["id"]))

            raw["buy"] = safe_float(fetch_setval(site, SILVER_BUY_ID))
            raw["sell"] = safe_float(fetch_setval(site, SILVER_SELL_ID))

            # NEW SCREEN VALUES
            sell22 = safe_float(fetch_setval(site, SELL_PRICE_22_ID))
            disc22 = safe_float(fetch_setval(site, DISCOUNT_22_ID))
            sell24 = safe_float(fetch_setval(site, SELL_PRICE_24_ID))
            disc24 = safe_float(fetch_setval(site, DISCOUNT_24_ID))

            out = {"status": "OK"}

            # ✅ FORMATTING RULES
            out["sell_price_22"] = fmt2(sell22)
            out["discount_22"] = fmt0(disc22)
            out["sell_price_24"] = fmt2(sell24)
            out["discount_24"] = fmt0(disc24)

            out["final_sell_price_22"] = fmt2(sell22 - disc22) if sell22 is not None and disc22 is not None else "INVALID"
            out["final_sell_price_24"] = fmt2(sell24 - disc24) if sell24 is not None and disc24 is not None else "INVALID"

            # ORIGINAL 4 SQUARES
            for k, cfg in ITEMS.items():
                if raw[k] is None:
                    out[k] = {"tag": cfg["tag"], "value": "INVALID"}
                else:
                    val = compute_final_4squares(gold, raw[k], cfg["use_0916"])
                    out[k] = {"tag": cfg["tag"], "value": f"{val:,.0f}"}

            # SILVER
            out["silver_buy"] = fmt0(compute_kilo_silver(silver, -raw["buy"])) if raw["buy"] is not None else "INVALID"
            out["silver_sell"] = fmt0(compute_kilo_silver(silver, raw["sell"])) if raw["sell"] is not None else "INVALID"

            return JSONResponse(out)

        except Exception:
            return JSONResponse({"status": "ERROR"})


@app.get("/api/xrates")
def api_xrates():
    try:
        return {"status": "OK", "items": fetch_xrates(ensure_site_id())}
    except:
        return {"status": "ERROR", "items": []}


@app.get("/api/discounts/{sec}")
def api_disc(sec: str):
    try:
        return {"status": "OK", "rows": fetch_discounts_section(ensure_site_id(), sec.upper())}
    except:
        return {"status": "ERROR", "rows": []}