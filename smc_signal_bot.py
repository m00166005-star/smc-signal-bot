#!/usr/bin/env python3

import os
import json
import requests
import time
from datetime import datetime, timezone

# ───────────────────────── CONFIG ─────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BASE_URL = "https://api.kucoin.com"

SYMBOLS = [
"BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
"DOGE-USDT","ADA-USDT","TRX-USDT","AVAX-USDT","LINK-USDT",
"DOT-USDT","MATIC-USDT","LTC-USDT","BCH-USDT","ATOM-USDT",
"NEAR-USDT","APT-USDT","ETC-USDT","UNI-USDT","FIL-USDT"
]

LTF = "15min"
ITF = "1hour"
HTF = "4hour"

MIN_SCORE = 75

STATE_FILE = "state.json"

# ───────────────────────── STATE ─────────────────────────
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def can_trade(symbol, direction, state):
    if symbol not in state:
        return True

    t = state[symbol]

    if t.get("status") == "OPEN":
        return False

    return True

def open_trade(symbol, sig, state):
    state[symbol] = {
        "status": "OPEN",
        "direction": sig["direction"],
        "entry": sig["price"],
        "time": str(datetime.now())
    }

# ───────────────────────── DATA ─────────────────────────
def get_klines(symbol, interval, limit=100):
    url = f"{BASE_URL}/api/v1/market/candles"
    params = {"symbol": symbol, "type": interval}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json().get("data", [])
        candles = []

        for d in reversed(data[:limit]):
            candles.append({
                "open": float(d[1]),
                "close": float(d[2]),
                "high": float(d[3]),
                "low": float(d[4]),
                "volume": float(d[5]),
            })

        return candles
    except:
        return []

# ───────────────────────── INDICATORS ─────────────────────────
def rsi(candles, p=14):
    closes = [c["close"] for c in candles]
    if len(closes) < p:
        return 50

    gains = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    ag = sum(gains[-p:]) / p
    al = sum(losses[-p:]) / p

    if al == 0:
        return 100

    rs = ag / al
    return 100 - (100 / (1 + rs))

def atr(candles, p=14):
    trs = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i-1]["close"]),
            abs(candles[i]["low"] - candles[i-1]["close"])
        )
        trs.append(tr)

    return sum(trs[-p:]) / max(1, min(p, len(trs)))

def ema(candles, p=50):
    closes = [c["close"] for c in candles]
    if len(closes) < p:
        return closes[-1] if closes else 0

    k = 2 / (p + 1)
    e = sum(closes[:p]) / p

    for price in closes[p:]:
        e = price * k + e * (1 - k)

    return e

# ───────────────────────── STRUCTURE ─────────────────────────
def structure(candles):
    highs = []
    lows = []

    for i in range(3, len(candles)-3):
        if all(candles[i]["high"] > candles[j]["high"] for j in range(i-3, i+4) if j != i):
            highs.append(candles[i]["high"])
        if all(candles[i]["low"] < candles[j]["low"] for j in range(i-3, i+4) if j != i):
            lows.append(candles[i]["low"])

    if len(highs) < 2:
        return "NEUTRAL"

    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "BULLISH"

    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "BEARISH"

    return "NEUTRAL"

# ───────────────────────── LIQUIDITY ─────────────────────────
def sweep(candles):
    if len(candles) < 10:
        return None

    last = candles[-1]
    prev_high = max(c["high"] for c in candles[-10:-1])
    prev_low = min(c["low"] for c in candles[-10:-1])

    if last["high"] > prev_high and last["close"] < prev_high:
        return "BEARISH"

    if last["low"] < prev_low and last["close"] > prev_low:
        return "BULLISH"

    return None

# ───────────────────────── ANALYZE ─────────────────────────
def analyze(symbol, state):

    htf = get_klines(symbol, HTF)
    itf = get_klines(symbol, ITF)
    ltf = get_klines(symbol, LTF)

    if not htf or not itf or not ltf:
        return None

    price = ltf[-1]["close"]

    r = rsi(ltf)
    a = atr(ltf)

    ema50 = ema(htf, 50)
    ema200 = ema(htf, 200)

    htf_struct = structure(htf)
    sw = sweep(ltf)

    results = []

    for direction in ["LONG", "SHORT"]:

        if not can_trade(symbol, direction, state):
            continue

        score = 0
        reasons = []

        # trend
        if direction == "LONG" and ema50 > ema200:
            score += 25
            reasons.append("Trend Bullish")

        if direction == "SHORT" and ema50 < ema200:
            score += 25
            reasons.append("Trend Bearish")

        # structure
        if direction == "LONG" and htf_struct == "BULLISH":
            score += 15
        if direction == "SHORT" and htf_struct == "BEARISH":
            score += 15

        # sweep
        if sw == "BULLISH" and direction == "LONG":
            score += 15
            reasons.append("Liquidity Sweep")

        if sw == "BEARISH" and direction == "SHORT":
            score += 15
            reasons.append("Liquidity Sweep")

        # RSI
        if direction == "LONG" and r < 40:
            score += 10
        if direction == "SHORT" and r > 60:
            score += 10

        # session bonus
        score += 5

        if score < MIN_SCORE:
            continue

        sl = price - a * 2 if direction == "LONG" else price + a * 2
        tp1 = price + a * 3 if direction == "LONG" else price - a * 3
        tp2 = price + a * 5 if direction == "LONG" else price - a * 5

        rr = abs(tp2 - price) / abs(sl - price)

        sig = {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "price": price,
            "sl": round(sl, 6),
            "tp1": round(tp1, 6),
            "tp2": round(tp2, 6),
            "rr": round(rr, 2),
            "rsi": r,
            "reasons": reasons
        }

        open_trade(symbol, sig, state)

        results.append(sig)

    return max(results, key=lambda x: x["score"]) if results else None

# ───────────────────────── TELEGRAM ─────────────────────────
def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def format(sig):
    emoji = "🟢" if sig["direction"] == "LONG" else "🔴"

    return f"""{emoji} SIGNAL
────────────────
{sig['symbol']} | {sig['direction']}
Score: {sig['score']}/100

Entry: {sig['price']}
SL: {sig['sl']}
TP1: {sig['tp1']}
TP2: {sig['tp2']}
RR: 1:{sig['rr']}

RSI: {sig['rsi']:.0f}
────────────────
"""

# ───────────────────────── MAIN LOOP ─────────────────────────
def main():

    print("Bot Running...")

    while True:

        state = load_state()

        for s in SYMBOLS:
            try:
                sig = analyze(s, state)
                if sig:
                    send(format(sig))
                    print("SIGNAL", s, sig["score"])
                else:
                    print("skip", s)

                time.sleep(1)

            except Exception as e:
                print("ERR", e)

        save_state(state)

        send("Scan done " + str(datetime.now()))

        time.sleep(900)  # 15 minutes

if __name__ == "__main__":
    main()
