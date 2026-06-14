#!/usr/bin/env python3

import os, json, time, requests
import numpy as np
from datetime import datetime

# ───────── CONFIG ─────────
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT = os.environ.get("TELEGRAM_CHAT_ID")

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

# ───────── STATE ─────────
def load_state():
    try:
        return json.load(open(STATE_FILE))
    except:
        return {}

def save_state(s):
    json.dump(s, open(STATE_FILE,"w"), indent=2)

# ───────── DATA ─────────
def candles(sym):
    try:
        r = requests.get(
            f"{BASE}/api/v1/market/candles",
            params={"symbol": sym, "type": TF}
        )
        data = r.json().get("data", [])
        return [{
            "o": float(x[1]),
            "c": float(x[2]),
            "h": float(x[3]),
            "l": float(x[4]),
            "v": float(x[5]),
        } for x in reversed(data[:120])]
    except:
        return []

# ───────── FEATURES ─────────
def features(c):
    if len(c) < 20:
        return np.zeros(6)

    return np.array([
        c[-1]["c"] - c[-2]["c"],
        c[-1]["h"] - c[-1]["l"],
        abs(c[-1]["c"] - c[-1]["o"]),
        np.mean([x["v"] for x in c[-10:]]),
        c[-1]["c"] - c[-10]["c"],
        np.std([x["c"] for x in c[-10:]])
    ])

# ───────── SIMPLE ML MODEL (no external dependency) ─────────
# pseudo probability model (trained offline style)
def ml_score(f):
    raw = (
        f[0]*0.3 +
        f[1]*0.2 +
        f[2]*0.2 +
        f[3]*0.1 +
        f[4]*0.2
    )

    prob = 1 / (1 + np.exp(-raw))  # sigmoid
    return prob

# ───────── REGIME ─────────
def regime(c):
    if len(c) < 20:
        return "CHOPPY"

    move = abs(c[-1]["c"] - c[-20]["c"])
    noise = np.mean([abs(x["h"]-x["l"]) for x in c[-20:]])

    if move > noise * 2:
        return "TREND"
    elif move < noise:
        return "RANGE"
    return "CHOPPY"

# ───────── STRUCTURE SIMPLE ─────────
def structure(c):
    highs = [c[i]["h"] for i in range(-10,-1)]
    lows = [c[i]["l"] for i in range(-10,-1)]

    if highs[-1] > max(highs[:-1]) and lows[-1] > min(lows[:-1]):
        return "BULL"
    if highs[-1] < max(highs[:-1]) and lows[-1] < min(lows[:-1]):
        return "BEAR"
    return "NEUTRAL"

# ───────── STATE CONTROL ─────────
def can_trade(sym, state):
    return sym not in state or state[sym]["status"] != "OPEN"

def open_trade(sym, sig, state):
    state[sym] = {
        "status": "OPEN",
        "dir": sig["dir"],
        "entry": sig["price"],
        "time": str(datetime.now())
    }

# ───────── ANALYZE ─────────
def analyze(sym, state):

    c = candles(sym)
    if not c:
        return None

    price = c[-1]["c"]

    f = features(c)
    ml = ml_score(f)

    reg = regime(c)
    st = structure(c)

    for d in ["LONG","SHORT"]:

        if not can_trade(sym, state):
            continue

        score = 0
        reasons = []

        # ML probability
        score += ml * 50

        # regime filter
        if reg == "TREND":
            score += 20
        else:
            score -= 20

        # structure
        if d == "LONG" and st == "BULL":
            score += 15
        if d == "SHORT" and st == "BEAR":
            score += 15

        # direction bias
        if d == "LONG" and f[4] > 0:
            score += 10
        if d == "SHORT" and f[4] < 0:
            score += 10

        if score < MIN_SCORE:
            continue

        sl = price * 0.98 if d == "LONG" else price * 1.02
        tp = price * 1.04 if d == "LONG" else price * 0.96

        sig = {
            "symbol": sym,
            "dir": d,
            "score": round(score,2),
            "prob": round(ml,2),
            "price": price,
            "sl": round(sl,6),
            "tp": round(tp,6),
            "regime": reg
        }

        open_trade(sym, sig, state)

        return sig

# ───────── TELEGRAM ─────────
def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT, "text": msg}
    )

def fmt(s):
    e = "🟢" if s["dir"]=="LONG" else "🔴"
    return f"""{e} QUANT SIGNAL
────────────
{s['symbol']} | {s['dir']}
Score: {s['score']}
Prob: {s['prob']}
Regime: {s['regime']}

Entry: {s['price']}
SL: {s['sl']}
TP: {s['tp']}
────────────
"""

# ───────── MAIN ─────────
def main():

    print("QUANT BOT RUNNING")

    while True:

        state = load_state()

        for s in SYMBOLS:

            sig = analyze(s, state)

            if sig:
                send(fmt(sig))
                print("SIGNAL", s)

            time.sleep(1)

        save_state(state)

        send("SCAN DONE " + str(datetime.now()))

        time.sleep(900)

if __name__ == "__main__":
    main()
