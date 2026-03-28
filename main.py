# main.py
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
SUCCESSFN_GOLD_SYMBOL = "LLGUSD"   # Gold for 4 squares
SUCCESSFN_SILVER_SYMBOL = "LLSUSD" # Silver for kilo silver boxes

SUCCESSFN_POLL_SECONDS = 15
SHAREPOINT_POLL_SECONDS = 300
XRATES_POLL_SECONDS = 300
DISCOUNTS_POLL_SECONDS = 300
DIAMOND_CALC_POLL_SECONDS = 300
ONHAND_POLL_SECONDS = 300

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
SILVER_BUY_ID = 5
SILVER_SELL_ID = 6
SILVER_MULT = 3.674
SILVER_TO_KILO = 32.15

# --------------------------
# NEW LUXURY SELL SCREEN CONFIG
# --------------------------
DISCOUNT_22_ID = 37
DISCOUNT_24_ID = 38
SELL_PRICE_22_ID = 39
SELL_PRICE_24_ID = 40

# --------------------------
# DISCOUNTS SCREENS CONFIG
# --------------------------
DISCOUNTS_SECTIONS = {
    "PAMP": (11, 21),
    "LOCAL": (22, 28),
    "VALCAMBI": (29, 36),
}

# --------------------------
# DIAMOND CALCULATOR CONFIG
# --------------------------
DIAMOND_LIST_NAME = "diamondpricecalculator"
DIAMOND_ITEM_ID = 1

DIAMOND_GOLDVALUE_FIELD = "goldvalue"
DIAMOND_DIAMONDVALUE_FIELD = "diamondvalue"
DIAMOND_MARGIN_FIELD = "margin"
DIAMOND_COLORSTONEVALUE_FIELD = "colorstonevalue"
DIAMOND_CERTVALUE_FIELD = "certvalue"
DIAMOND_MAKING_FIELD = "making"

# --------------------------
# ONHAND 22K CONFIG
# --------------------------
ONHAND_LIST_NAME = os.environ.get("ONHAND_LIST_NAME", "onhand")
ONHAND_COUNT_FIELD = os.environ.get("ONHAND_COUNT_FIELD", "count")
ONHAND_WEIGHT_FIELD = os.environ.get("ONHAND_WEIGHT_FIELD", "weight")

ONHAND_22K_ROWS = [
    {"label": "CHAIN",     "id": 1,  "weight_divisor": 1},
    {"label": "BANGLE",    "id": 4,  "weight_divisor": 1},
    {"label": "RING",      "id": 7,  "weight_divisor": 1},
    {"label": "NECKLACE",  "id": 2,  "weight_divisor": 1},
    {"label": "EARRING",   "id": 3,  "weight_divisor": 1},
    {"label": "PENDANT",   "id": 6,  "weight_divisor": 1},
    {"label": "BRACELET",  "id": 5,  "weight_divisor": 1},
    {"label": "ANKLET",    "id": 67, "weight_divisor": 1},
    {"label": "BACKCHAIN", "id": 9,  "weight_divisor": 1},
]

# --------------------------
# GRAPH / SHAREPOINT CONFIG (Render env vars)
# --------------------------
TENANT_ID = os.environ["TENANT_ID"]
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]

SP_HOST = os.environ.get("SP_HOST", "anvarluxuryjewellery.sharepoint.com")
SP_SITE_PATH = os.environ.get("SP_SITE_PATH", "/sites/PRODUCTENTRY")

# list for values (IDs 1..6, 11..36, 37..40)
SP_LIST_NAME = os.environ.get("SP_LIST_NAME", "staffinstructions")
SP_COLUMN_NAME = os.environ.get("SP_COLUMN_NAME", "setval")
SP_CERTCHARGE_COLUMN = os.environ.get("SP_CERTCHARGE_COLUMN", "certcharge")

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


def safe_str(x) -> str:
    if x is None:
        return ""
    return str(x).strip()


def fmt0(x):
    if x is None:
        return "INVALID"
    return f"{x:,.0f}"


def fmt2(x):
    if x is None:
        return "INVALID"
    return f"{x:,.2f}"


def fmt0_or_dash(x):
    if x is None:
        return "—"
    return f"{x:,.0f}"


def parse_successfn_symbol(text: str, symbol: str):
    records = text.replace("\r", "\n").split()
    for rec in records:
        parts = [p.strip() for p in rec.split(",")]
        if len(parts) >= 2 and parts[0] == symbol:
            return safe_float(parts[1])
    return None


def fetch_successfn_prices():
    r = requests.get(
        SUCCESSFN_API_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
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


def fetch_item_fields(site_id: str, item_id: int):
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        f"/lists/{SP_LIST_NAME}"
        f"/items/{item_id}?expand=fields"
    )
    data = graph_get(url)
    return data.get("fields", {}) or {}


def fetch_item_fields_from_list(site_id: str, list_name: str, item_id: int):
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}"
        f"/lists/{list_name}"
        f"/items/{item_id}?expand=fields"
    )
    data = graph_get(url)
    return data.get("fields", {}) or {}


def fetch_setval(site_id: str, item_id: int):
    fields = fetch_item_fields(site_id, item_id)
    return fields.get(SP_COLUMN_NAME, "")


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
        out.append({
            "rate": "" if fields.get(XRATES_RATE_FIELD) is None else str(fields.get(XRATES_RATE_FIELD)),
            "type": "" if fields.get(XRATES_TYPE_FIELD) is None else str(fields.get(XRATES_TYPE_FIELD)),
        })
    return out


def fetch_discounts_section(site_id: str, section_name: str):
    if section_name not in DISCOUNTS_SECTIONS:
        return []

    start_id, end_id = DISCOUNTS_SECTIONS[section_name]
    rows = []
    for item_id in range(start_id, end_id + 1):
        fields = fetch_item_fields(site_id, item_id)

        typ = safe_str(fields.get("Title") or fields.get("title"))
        disc = safe_str(fields.get(SP_COLUMN_NAME))
        cert = safe_str(fields.get(SP_CERTCHARGE_COLUMN))

        rows.append({
            "id": item_id,
            "type": typ,
            "disc": disc,
            "cert_charge": cert,
        })
    return rows


def fetch_diamond_calc_values(site_id: str):
    fields = fetch_item_fields_from_list(site_id, DIAMOND_LIST_NAME, DIAMOND_ITEM_ID)
    return {
        "goldvalue": safe_float(fields.get(DIAMOND_GOLDVALUE_FIELD)),
        "diamondvalue": safe_float(fields.get(DIAMOND_DIAMONDVALUE_FIELD)),
        "margin": safe_float(fields.get(DIAMOND_MARGIN_FIELD)),
        "colorstonevalue": safe_float(fields.get(DIAMOND_COLORSTONEVALUE_FIELD)),
        "certvalue": safe_float(fields.get(DIAMOND_CERTVALUE_FIELD)),
        "making": safe_float(fields.get(DIAMOND_MAKING_FIELD)),
    }


def fetch_onhand_22k_rows(site_id: str):
    rows = []
    for cfg in ONHAND_22K_ROWS:
        fields = fetch_item_fields_from_list(site_id, ONHAND_LIST_NAME, cfg["id"])

        count_val = safe_float(fields.get(ONHAND_COUNT_FIELD))
        weight_val = safe_float(fields.get(ONHAND_WEIGHT_FIELD))

        divisor = cfg.get("weight_divisor", 1) or 1
        if weight_val is not None:
            weight_val = weight_val / divisor

        rows.append({
            "label": cfg["label"],
            "count": fmt0_or_dash(count_val),
            "weight": fmt0_or_dash(weight_val),
        })
    return rows


def compute_diamond_sell_price(gold_weight, diamond_weight, color_stone_weight, cfg):
    goldvalue = cfg.get("goldvalue")
    diamondvalue = cfg.get("diamondvalue")
    margin = cfg.get("margin")
    colorstonevalue = cfg.get("colorstonevalue")
    certvalue = cfg.get("certvalue")
    making = cfg.get("making")

    if (
        goldvalue is None or
        diamondvalue is None or
        margin is None or
        colorstonevalue is None or
        certvalue is None or
        making is None
    ):
        return None

    if gold_weight is None or diamond_weight is None or color_stone_weight is None:
        return None

    result_a = gold_weight * goldvalue
    result_b = gold_weight * making * 3.674
    result_c = diamond_weight * diamondvalue * 3.674
    result_d = color_stone_weight * colorstonevalue * 3.674
    result_e = result_a + result_b + result_c + result_d + certvalue

    final_price = result_e * margin
    return final_price


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

_success_cache = {"gold": None, "silver": None, "ts": 0.0}
_sharepoint_cache = {"vals": None, "ts": 0.0}
_xrates_cache = {"items": None, "ts": 0.0}
_diamond_calc_cache = {"vals": None, "ts": 0.0}
_onhand_22k_cache = {"rows": None, "ts": 0.0}

_discounts_cache = {
    "PAMP": {"rows": None, "ts": 0.0},
    "LOCAL": {"rows": None, "ts": 0.0},
    "VALCAMBI": {"rows": None, "ts": 0.0},
}


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

    for key, cfg in ITEMS.items():
        vals[key] = fetch_setval(site_id, cfg["id"])

    vals["SILVER_BUY_ID5"] = fetch_setval(site_id, SILVER_BUY_ID)
    vals["SILVER_SELL_ID6"] = fetch_setval(site_id, SILVER_SELL_ID)

    vals["DISCOUNT_22_ID37"] = fetch_setval(site_id, DISCOUNT_22_ID)
    vals["DISCOUNT_24_ID38"] = fetch_setval(site_id, DISCOUNT_24_ID)
    vals["SELL_PRICE_22_ID39"] = fetch_setval(site_id, SELL_PRICE_22_ID)
    vals["SELL_PRICE_24_ID40"] = fetch_setval(site_id, SELL_PRICE_24_ID)

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


def get_discounts_section(site_id: str, section_name: str):
    now = time.time()
    cache = _discounts_cache.get(section_name)
    if cache and cache["rows"] is not None and (now - cache["ts"]) < DISCOUNTS_POLL_SECONDS:
        return cache["rows"]

    rows = fetch_discounts_section(site_id, section_name)
    if cache is not None:
        cache["rows"] = rows
        cache["ts"] = now
    return rows


def get_diamond_calc_values(site_id: str):
    now = time.time()
    if _diamond_calc_cache["vals"] is not None and (now - _diamond_calc_cache["ts"]) < DIAMOND_CALC_POLL_SECONDS:
        return _diamond_calc_cache["vals"]

    vals = fetch_diamond_calc_values(site_id)
    _diamond_calc_cache["vals"] = vals
    _diamond_calc_cache["ts"] = now
    return vals


def get_onhand_22k(site_id: str):
    now = time.time()
    if _onhand_22k_cache["rows"] is not None and (now - _onhand_22k_cache["ts"]) < ONHAND_POLL_SECONDS:
        return _onhand_22k_cache["rows"]

    rows = fetch_onhand_22k_rows(site_id)
    _onhand_22k_cache["rows"] = rows
    _onhand_22k_cache["ts"] = now
    return rows


def blank_payload(status: str):
    return {
        "status": status,

        "sell_price_22": "—",
        "discount_22": "—",
        "final_sell_price_22": "—",

        "sell_price_24": "—",
        "discount_24": "—",
        "final_sell_price_24": "—",

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
                return JSONResponse(blank_payload("SUCCESSFN ERROR (LLSUSD)"))

            raw_map = get_sharepoint_values(site_id)
            out = {"status": "OK"}

            # New luxury sell screen values
            sell22 = safe_float(raw_map.get("SELL_PRICE_22_ID39"))
            disc22 = safe_float(raw_map.get("DISCOUNT_22_ID37"))
            sell24 = safe_float(raw_map.get("SELL_PRICE_24_ID40"))
            disc24 = safe_float(raw_map.get("DISCOUNT_24_ID38"))

            out["sell_price_22"] = fmt2(sell22)
            out["discount_22"] = fmt0(disc22)
            out["sell_price_24"] = fmt2(sell24)
            out["discount_24"] = fmt0(disc24)

            out["final_sell_price_22"] = (
                "INVALID" if sell22 is None or disc22 is None else fmt2(sell22 - disc22)
            )
            out["final_sell_price_24"] = (
                "INVALID" if sell24 is None or disc24 is None else fmt2(sell24 - disc24)
            )

            # Existing 4 squares
            for key, cfg in ITEMS.items():
                sp_val = safe_float(raw_map.get(key))
                if sp_val is None:
                    out[key] = {"tag": cfg["tag"], "value": "INVALID"}
                    continue
                final = compute_final_4squares(gold_val, sp_val, cfg["use_0916"])
                out[key] = {"tag": cfg["tag"], "value": f"{final:,.0f}"}

            # Existing silver values - now AED/GRAM instead of AED/KG
            id5 = safe_float(raw_map.get("SILVER_BUY_ID5"))
            id6 = safe_float(raw_map.get("SILVER_SELL_ID6"))

            out["silver_buy"] = "INVALID" if id5 is None else f"{(compute_kilo_silver(silver_val, -id5) / 1000):,.2f}"
            out["silver_sell"] = "INVALID" if id6 is None else f"{(compute_kilo_silver(silver_val, +id6) / 1000):,.2f}"

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


@app.get("/api/discounts/{section_name}")
def api_discounts(section_name: str):
    sec = (section_name or "").strip().upper()
    with _lock:
        try:
            site_id = ensure_site_id()
        except Exception:
            return JSONResponse({"status": "SHAREPOINT ERROR (SITE)", "section": sec, "rows": []})

        try:
            if sec not in DISCOUNTS_SECTIONS:
                return JSONResponse({"status": "INVALID SECTION", "section": sec, "rows": []})

            rows = get_discounts_section(site_id, sec)
            return JSONResponse({"status": "OK", "section": sec, "rows": rows})
        except Exception:
            return JSONResponse({"status": "SHAREPOINT ERROR (DISCOUNTS)", "section": sec, "rows": []})


@app.get("/api/diamond-config")
def api_diamond_config():
    with _lock:
        try:
            site_id = ensure_site_id()
        except Exception:
            return JSONResponse({
                "status": "SHAREPOINT ERROR (SITE)",
                "goldvalue": None,
                "diamondvalue": None,
                "margin": None,
                "colorstonevalue": None,
                "certvalue": None,
                "making": None,
            })

        try:
            vals = get_diamond_calc_values(site_id)
            out = {"status": "OK"}
            out.update(vals)
            return JSONResponse(out)
        except Exception:
            return JSONResponse({
                "status": "SHAREPOINT ERROR (DIAMOND CALC)",
                "goldvalue": None,
                "diamondvalue": None,
                "margin": None,
                "colorstonevalue": None,
                "certvalue": None,
                "making": None,
            })


@app.get("/api/diamond-calc")
def api_diamond_calc(gold_weight: str = "", diamond_weight: str = "", color_stone_weight: str = ""):
    with _lock:
        try:
            site_id = ensure_site_id()
        except Exception:
            return JSONResponse({
                "status": "SHAREPOINT ERROR (SITE)",
                "diamond_sell_price": "—",
            })

        try:
            # If ANY input is blank, show 0 AED
            if not str(gold_weight).strip() or not str(diamond_weight).strip() or not str(color_stone_weight).strip():
                return JSONResponse({
                    "status": "OK",
                    "diamond_sell_price": "0",
                })

            gold_w = safe_float(gold_weight)
            diamond_w = safe_float(diamond_weight)
            color_w = safe_float(color_stone_weight)

            if gold_w is None or diamond_w is None or color_w is None:
                return JSONResponse({
                    "status": "OK",
                    "diamond_sell_price": "0",
                })

            cfg = get_diamond_calc_values(site_id)
            final_price = compute_diamond_sell_price(gold_w, diamond_w, color_w, cfg)

            if final_price is None:
                return JSONResponse({
                    "status": "SHAREPOINT ERROR (DIAMOND CALC)",
                    "diamond_sell_price": "INVALID",
                })

            return JSONResponse({
                "status": "OK",
                "diamond_sell_price": f"{final_price:,.0f}",
            })

        except Exception:
            return JSONResponse({
                "status": "SHAREPOINT ERROR (DIAMOND CALC)",
                "diamond_sell_price": "INVALID",
            })


@app.get("/api/onhand-22k")
def api_onhand_22k():
    with _lock:
        try:
            site_id = ensure_site_id()
        except Exception:
            return JSONResponse({
                "status": "SHAREPOINT ERROR (SITE)",
                "rows": [],
            })

        try:
            rows = get_onhand_22k(site_id)
            return JSONResponse({
                "status": "OK",
                "rows": rows,
            })
        except Exception:
            return JSONResponse({
                "status": "SHAREPOINT ERROR (ONHAND 22K)",
                "rows": [],
            })