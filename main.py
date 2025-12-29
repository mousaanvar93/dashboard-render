import os
import json
import time
import threading
import requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

# --------------------------
# SUCCESSFN
# --------------------------
SUCCESSFN_API_URL = "https://www.successfn.com/wp-content/themes/neve/page-templates/getprice.php?site=cfgs"
SUCCESSFN_SYMBOL = "LLGUSD"  # change if needed

# --------------------------
# YOUR MATH
# --------------------------
DIVISOR = 31.1035
MULT_A = 3.674
MULT_B = 0.916

ITEMS = {
    "TL": {"use_0916": True,  "tag": "22EXCH"},
    "BL": {"use_0916": False, "tag": "24EXCH"},
    "TR": {"use_0916": True,  "tag": "22CASH"},
    "BR": {"use_0916": False, "tag": "24CASH"},
}

POLL_SECONDS = 10

# --------------------------
# SECURITY (Render env var)
# --------------------------
API_KEY = os.environ.get("DASHBOARD_API_KEY", "CHANGE_ME_NOW")

# Persistent file path (we'll set this to /var/data/store.json on Render disk)
STORE_PATH = os.environ.get("STORE_PATH", "store.json")


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

    # Records are separated by whitespace/newlines
    records = text.replace("\r", "\n").split()
    for rec in records:
        parts = [p.strip() for p in rec.split(",") if p.strip()]
        # Example: LLGUSD,4531.91,4531.91,...
        if len(parts) >= 2 and parts[0] == SUCCESSFN_SYMBOL:
            return safe_float(parts[1])
    return None


def compute_final(success_val, subtract_val, use_0916):
    base = (success_val / DIVISOR) * MULT_A
    if use_0916:
        base *= MULT_B
    return base - subtract_val


def load_store():
    if not os.path.exists(STORE_PATH):
        return {"TL": 0.0, "TR": 0.0, "BL": 0.0, "BR": 0.0}
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in ["TL", "TR", "BL", "BR"]:
            data.setdefault(k, 0.0)
        return data
    except Exception:
        return {"TL": 0.0, "TR": 0.0, "BL": 0.0, "BR": 0.0}


def save_store(data):
    os.makedirs(os.path.dirname(STORE_PATH) or ".", exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


store = load_store()

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
    try:
        success_val = fetch_successfn_price()
        if success_val is None:
            return blank_payload("SUCCESSFN ERROR")
    except Exception:
        return blank_payload("SUCCESSFN ERROR")

    out = {"status": "OK"}
    for k, cfg in ITEMS.items():
        subtract_val = safe_float(store.get(k))
        if subtract_val is None:
            out[k] = {"tag": cfg["tag"], "value": "INVALID"}
            continue
        final = compute_final(success_val, subtract_val, cfg["use_0916"])
        out[k] = {"tag": cfg["tag"], "value": f"{final:,.0f}"}
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


@app.get("/api/store")
def api_store():
    return store


def require_key(x_api_key: str | None):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.post("/api/set")
async def api_set(body: dict, x_api_key: str | None = Header(default=None)):
    """
    POST JSON:
    {"TL": 10, "TR": 20, "BL": 30, "BR": 40}
    You can send only some keys and it will update only those.
    """
    require_key(x_api_key)

    changed = False
    for k in ["TL", "TR", "BL", "BR"]:
        if k in body:
            v = safe_float(body[k])
            if v is None:
                raise HTTPException(status_code=400, detail=f"{k} must be a number")
            store[k] = float(v)
            changed = True

    if changed:
        save_store(store)

    return {"ok": True, "store": store}
