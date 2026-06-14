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
LOG_FILE = "scan_log.txt"
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


# ================= LOG =================
def log(symbol, score, status, reasons):
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.now()} | {symbol} | {score} | {status} | {reasons}\n")


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

    k = 2/(p+1)
    e = sum(c[:p])/p
    for v in c[p:]:
        e = v*k + e*(1-k)
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

    return 100 - (100/(1 + up/down))


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


# ================= TRADE LOCK =================
def can_trade(symbol, state):
    return symbol not in state or state[symbol]["status"] != "OPEN"


# ================= TELEGRAM =================
def send(msg):
    if TOKEN and CHAT_ID:
        session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg},
            timeout=8
        )


def fmt(sig):
    e = "🟢" if sig["dir"] == "LONG" else "🔴"
    return f"""{e} SIGNAL
────────────
{sig['symbol']} | {sig['dir']}
Score: {sig['score']}
Entry: {sig['price']}
SL: {sig['sl']}
TP: {sig['tp']}
────────────
"""


# ================= ANALYZE =================
def analyze(symbol, state):

    c = candles(symbol)
    if not c:
        return None

    price = c[-1]["c"]

    e50 = ema(c, 50)
    e200 = ema(c, 200)
    r = rsi(c)
    a = atr(c)
    tr = trend(c)

    if not can_trade(symbol, state):
        log(symbol, 0, "SKIP", ["OPEN TRADE"])
        return None

    for d in ["LONG", "SHORT"]:

        score = 0
        reasons = []

        if d == "LONG" and e50 > e200:
            score += 35
            reasons.append("Trend Up")

        if d == "SHORT" and e50 < e200:
            score += 35
            reasons.append("Trend Down")

        if d == "LONG" and tr == "BULL":
            score += 20
            reasons.append("Structure Bull")

        if d == "SHORT" and tr == "BEAR":
            score += 20
            reasons.append("Structure Bear")

        if d == "LONG" and r < 45:
            score += 10
            reasons.append("RSI Low")

        if d == "SHORT" and r > 55:
            score += 10
            reasons.append("RSI High")

        if score < MIN_SCORE:
            log(symbol, score, "REJECT", reasons)
            return None

        sl = price - a*2 if d == "LONG" else price + a*2
        tp = price + a*3 if d == "LONG" else price - a*3

        sig = {
            "symbol": symbol,
            "dir": d,
            "score": score,
            "price": price,
            "sl": sl,
            "tp": tp
        }

        log(symbol, score, "ACCEPT", reasons)
        state[symbol] = {"status": "OPEN", "dir": d, "time": str(datetime.now())}

        return sig

    return None


# ================= MAIN LOOP =================
def main():

    print("BOT STARTED")

    while True:

        state = load_state()

        for s in SYMBOLS:

            print("[SCAN]", s, datetime.now())

            sig = analyze(s, state)

            if sig:
                send(fmt(sig))
                print("SIGNAL:", s)

            time.sleep(0.3)

        save_state(state)

        send("SCAN DONE " + str(datetime.now()))

        time.sleep(900)


if __name__ == "__main__":
    main()
    
