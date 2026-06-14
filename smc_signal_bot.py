import os
import json
import time
import requests
from datetime import datetime

# ================= CONFIG =================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BASE = "https://api.kucoin.com"

SYMBOLS = [
"BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
"DOGE-USDT","ADA-USDT","TRX-USDT","AVAX-USDT","LINK-USDT",
"DOT-USDT","MATIC-USDT","LTC-USDT","BCH-USDT","ATOM-USDT",
"NEAR-USDT","APT-USDT","ETC-USDT","UNI-USDT","FIL-USDT"
]

TF = "1hour"
STATE_FILE = "state.json"
MIN_SCORE = 70

session = requests.Session()

# ================= STATE =================
def load_state():
    try:
        return json.load(open(STATE_FILE))
    except:
        return {}

def save_state(s):
    json.dump(s, open(STATE_FILE, "w"), indent=2)

# ================= DATA =================
def candles(symbol):
    try:
        r = session.get(
            f"{BASE}/api/v1/market/candles",
            params={"symbol": symbol, "type": TF},
            timeout=8
        )
        data = r.json().get("data", [])
        return [{
            "c": float(x[2]),
            "h": float(x[3]),
            "l": float(x[4]),
        } for x in reversed(data[:80])]
    except:
        return []

# ================= INDICATORS =================
def ema(data, p):
    c = [x["c"] for x in data]
    if len(c) < p:
        return c[-1] if c else 0

    k = 2 / (p + 1)
    e = sum(c[:p]) / p

    for v in c[p:]:
        e = v * k + e * (1 - k)

    return e


def rsi(data):
    c = [x["c"] for x in data]
    if len(c) < 10:
        return 50

    up = down = 0

    for i in range(-10, -1):
        diff = c[i] - c[i-1]
        if diff > 0:
            up += diff
        else:
            down -= diff

    if down == 0:
        return 100

    return 100 - (100 / (1 + up / down))


def atr(data):
    tr = []
    for i in range(1, len(data)):
        tr.append(max(
            data[i]["h"] - data[i]["l"],
            abs(data[i]["h"] - data[i-1]["c"]),
            abs(data[i]["l"] - data[i-1]["c"])
        ))
    return sum(tr[-10:]) / max(1, len(tr[-10:]))

# ================= TREND =================
def trend(data):
    highs = [x["h"] for x in data[-8:]]
    lows = [x["l"] for x in data[-8:]]

    if highs[-1] > max(highs[:-1]) and lows[-1] > min(lows[:-1]):
        return "BULL"
    if highs[-1] < max(highs[:-1]) and lows[-1] < min(lows[:-1]):
        return "BEAR"
    return "NEUTRAL"

# ================= TELEGRAM LIVE =================
def send_live():
    r = session.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": "📊 Starting live scan..."}
    )
    return r.json()["result"]["message_id"]


def edit_live(mid, text):
    session.post(
        f"https://api.telegram.org/bot{TOKEN}/editMessageText",
        json={
            "chat_id": CHAT_ID,
            "message_id": mid,
            "text": text
        }
    )

# ================= ANALYZE =================
def analyze(symbol):

    c = candles(symbol)
    if not c:
        return None

    price = c[-1]["c"]

    e50 = ema(c, 50)
    e200 = ema(c, 200)
    r = rsi(c)
    a = atr(c)
    tr = trend(c)

    for d in ["LONG", "SHORT"]:

        score = 0

        if d == "LONG" and e50 > e200:
            score += 35

        if d == "SHORT" and e50 < e200:
            score += 35

        if d == "LONG" and tr == "BULL":
            score += 20

        if d == "SHORT" and tr == "BEAR":
            score += 20

        if d == "LONG" and r < 45:
            score += 10

        if d == "SHORT" and r > 55:
            score += 10

        if score >= MIN_SCORE:

            sl = price - a * 2 if d == "LONG" else price + a * 2
            tp = price + a * 3 if d == "LONG" else price - a * 3

            return {
                "symbol": symbol,
                "dir": d,
                "score": score,
                "price": price,
                "sl": sl,
                "tp": tp
            }

    return None

# ================= DASHBOARD =================
def build_dashboard(signals, scanned):

    text = "📊 LIVE CRYPTO SCANNER\n"
    text += "────────────────────\n"
    text += f"⏱ {datetime.now()}\n"
    text += f"🔍 Scanned: {len(scanned)}\n"
    text += f"🎯 Signals: {len(signals)}\n"
    text += "────────────────────\n"

    for s in signals[-10:]:

        e = "🟢" if s["dir"] == "LONG" else "🔴"

        text += f"{e} {s['symbol']} | {s['score']} | {s['dir']}\n"

    if not signals:
        text += "No valid signals\n"

    return text

# ================= MAIN LOOP =================
def main():

    print("LIVE BOT STARTED")

    mid = send_live()

    state = load_state()

    while True:

        signals = []
        scanned = []

        for s in SYMBOLS:

            scanned.append(s)

            sig = analyze(s)

            if sig:
                signals.append(sig)

            time.sleep(0.3)

        text = build_dashboard(signals, scanned)

        edit_live(mid, text)

        save_state(state)

        time.sleep(15)

# ================= RUN =================
if __name__ == "__main__":
    main()
