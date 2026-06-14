#!/usr/bin/env python3

import os
import json
import time
import requests
from datetime import datetime

# ───── CONFIG ─────
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BASE = "https://api.kucoin.com"

SYMBOLS = [
"BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
"DOGE-USDT","ADA-USDT","TRX-USDT","AVAX-USDT","LINK-USDT",
"DOT-USDT","MATIC-USDT","LTC-USDT","BCH-USDT","ATOM-USDT",
"NEAR-USDT","APT-USDT","ETC-USDT","UNI-USDT","FIL-USDT",
"ARB-USDT","OP-USDT","INJ-USDT","SEI-USDT","SUI-USDT",
"PEPE-USDT","FLOKI-USDT","GALA-USDT","SAND-USDT","AXS-USDT",
"IMX-USDT","RNDR-USDT","AAVE-USDT","CRV-USDT","MKR-USDT",
"XLM-USDT","VET-USDT","HBAR-USDT","ICP-USDT","QNT-USDT",
"ALGO-USDT","THETA-USDT","EOS-USDT","XTZ-USDT","KAVA-USDT",
"ZEC-USDT","DASH-USDT","LDO-USDT","AR-USDT","STX-USDT"
]

TF = "1hour"
STATE_FILE = "state.json"
MIN_SCORE = 60


# ───── STATE ─────
def load_state():
    try:
        return json.load(open(STATE_FILE))
    except:
        return {}

def save_state(s):
    json.dump(s, open(STATE_FILE, "w"), indent=2)


# ───── DATA ─────
def candles(symbol):
    try:
        r = requests.get(
            f"{BASE}/api/v1/market/candles",
            params={"symbol": symbol, "type": TF},
            timeout=10
        )
        data = r.json().get("data", [])
        return [{
            "o": float(x[1]),
            "c": float(x[2]),
            "h": float(x[3]),
            "l": float(x[4]),
            "v": float(x[5]),
        } for x in reversed(data[:100])]
    except:
        return []


# ───── INDICATORS ─────
def ema(data, period):
    prices = [x["c"] for x in data]
    if len(prices) < period:
        return prices[-1] if prices else 0

    k = 2 / (period + 1)
    e = sum(prices[:period]) / period

    for p in prices[period:]:
        e = p * k + e * (1 - k)

    return e


def rsi(data, period=14):
    prices = [x["c"] for x in data]
    if len(prices) < period + 1:
        return 50

    gains = 0
    losses = 0

    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff

    if losses == 0:
        return 100

    rs = gains / losses
    return 100 - (100 / (1 + rs))


def atr(data):
    trs = []
    for i in range(1, len(data)):
        tr = max(
            data[i]["h"] - data[i]["l"],
            abs(data[i]["h"] - data[i-1]["c"]),
            abs(data[i]["l"] - data[i-1]["c"])
        )
        trs.append(tr)

    return sum(trs[-14:]) / max(1, len(trs[-14:]))


# ───── STRUCTURE ─────
def trend(data):
    highs = [x["h"] for x in data[-10:]]
    lows = [x["l"] for x in data[-10:]]

    if highs[-1] > max(highs[:-1]) and lows[-1] > min(lows[:-1]):
        return "BULL"
    if highs[-1] < max(highs[:-1]) and lows[-1] < min(lows[:-1]):
        return "BEAR"
    return "NEUTRAL"


# ───── STATE CHECK ─────
def can_trade(symbol, state):
    return symbol not in state or state[symbol]["status"] != "OPEN"


def open_trade(symbol, sig, state):
    state[symbol] = {
        "status": "OPEN",
        "dir": sig["dir"],
        "entry": sig["price"],
        "time": str(datetime.now())
    }


# ───── ANALYZE ─────
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

    for d in ["LONG", "SHORT"]:

        if not can_trade(symbol, state):
            continue

        score = 0
        reasons = []

        # trend
        if d == "LONG" and e50 > e200:
            score += 30
            reasons.append("Trend Up")

        if d == "SHORT" and e50 < e200:
            score += 30
            reasons.append("Trend Down")

        # structure
        if d == "LONG" and tr == "BULL":
            score += 20

        if d == "SHORT" and tr == "BEAR":
            score += 20

        # RSI
        if d == "LONG" and r < 45:
            score += 10

        if d == "SHORT" and r > 55:
            score += 10

        score += 5

        if score < MIN_SCORE:
            continue

        sl = price - (a * 2) if d == "LONG" else price + (a * 2)
        tp = price + (a * 3) if d == "LONG" else price - (a * 3)

        sig = {
            "symbol": symbol,
            "dir": d,
            "score": round(score, 2),
            "price": price,
            "sl": round(sl, 6),
            "tp": round(tp, 6),
            "rsi": r
        }

        open_trade(symbol, sig, state)

        return sig

    return None


# ───── TELEGRAM ─────
def send(msg):
    if not TOKEN or not CHAT_ID:
        return

    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg}
    )


def format(sig):
    e = "🟢" if sig["dir"] == "LONG" else "🔴"

    return f"""{e} SIGNAL
────────────
{sig['symbol']} | {sig['dir']}
Score: {sig['score']}

Entry: {sig['price']}
SL: {sig['sl']}
TP: {sig['tp']}
RSI: {sig['rsi']}
────────────
"""


# ───── MAIN ─────
def main():

    print("BOT STARTED")

    while True:

        state = load_state()

        for s in SYMBOLS:

            sig = analyze(s, state)

            if sig:
                send(format(sig))
                print("SIGNAL", s, sig["score"])

            time.sleep(1)

        save_state(state)

        send("SCAN DONE " + str(datetime.now()))

        time.sleep(900)


if __name__ == "__main__":
    main()
