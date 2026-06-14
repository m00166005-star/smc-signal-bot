#!/usr/bin/env python3

import os
import requests
import time
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BASE_URL = "https://api.kucoin.com"

SYMBOLS = [
"BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
"DOGE-USDT","ADA-USDT","TRX-USDT","AVAX-USDT","LINK-USDT",
"DOT-USDT","MATIC-USDT","LTC-USDT","BCH-USDT","ATOM-USDT",
"NEAR-USDT","APT-USDT","ETC-USDT","UNI-USDT","FIL-USDT"
]

# ───────────────────────── TIMEFRAMES ─────────────────────────
HTF = "4hour"
ITF = "1hour"
LTF = "15min"

MIN_SCORE = 80

# ───────────────────────── DATA ─────────────────────────
def get_klines(symbol, interval, limit=100):
    url = f"{BASE_URL}/api/v1/market/candles"
    params = {"symbol": symbol, "type": interval}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        candles = []
        for d in reversed(data.get("data", [])[:limit]):
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

# ───────────────────────── STRUCTURE ─────────────────────────
def find_swing_points(candles, lookback=3):
    highs, lows = [], []
    n = len(candles)
    for i in range(lookback, n - lookback):
        if all(candles[i]["high"] > candles[j]["high"] for j in range(i-lookback, i+lookback+1) if j != i):
            highs.append(candles[i]["high"])
        if all(candles[i]["low"] < candles[j]["low"] for j in range(i-lookback, i+lookback+1) if j != i):
            lows.append(candles[i]["low"])
    return highs, lows

def detect_structure(candles):
    highs, lows = find_swing_points(candles)
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", None

    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "BULLISH", None
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "BEARISH", None

    return "NEUTRAL", None

# ───────────────────────── INDICATORS ─────────────────────────
def calc_rsi(candles, p=14):
    closes = [c["close"] for c in candles]
    if len(closes) < p + 1:
        return 50

    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]

    avg_gain = sum(gains[-p:]) / p
    avg_loss = sum(losses[-p:]) / p

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_atr(candles, p=14):
    trs = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i-1]["close"]),
            abs(candles[i]["low"] - candles[i-1]["close"])
        )
        trs.append(tr)

    if not trs:
        return 0

    return sum(trs[-p:]) / min(p, len(trs))

def calc_ema(candles, p=50):
    closes = [c["close"] for c in candles]
    if len(closes) < p:
        return closes[-1] if closes else 0

    k = 2 / (p + 1)
    ema = sum(closes[:p]) / p

    for price in closes[p:]:
        ema = price * k + ema * (1 - k)

    return ema

# ───────────────────────── LIQUIDITY SWEEP ─────────────────────────
def liquidity_sweep(candles):
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

# ───────────────────────── CHOCH ─────────────────────────
def detect_choch(candles):
    highs, lows = find_swing_points(candles)
    if len(highs) < 3:
        return None

    if highs[-1] > highs[-2] and lows[-1] < lows[-2]:
        return "CHOCH"

    return None

# ───────────────────────── SESSION ─────────────────────────
def session():
    h = datetime.now(timezone.utc).hour
    if 7 <= h < 12:
        return "LONDON"
    if 12 <= h < 20:
        return "NEWYORK"
    return "ASIAN"

# ───────────────────────── ANALYZE ─────────────────────────
def analyze(symbol):
    htf = get_klines(symbol, HTF)
    itf = get_klines(symbol, ITF)
    ltf = get_klines(symbol, LTF)

    if not htf or not itf or not ltf:
        return None

    price = ltf[-1]["close"]

    rsi = calc_rsi(ltf)
    atr = calc_atr(ltf)

    ema50 = calc_ema(htf, 50)
    ema200 = calc_ema(htf, 200)

    htf_struct, _ = detect_structure(htf)
    sweep = liquidity_sweep(ltf)
    choch = detect_choch(itf)

    sess = session()

    results = []

    for direction in ["LONG", "SHORT"]:
        score = 0
        reasons = []

        # trend
        if direction == "LONG" and ema50 > ema200:
            score += 20
            reasons.append("Trend Bullish")
        if direction == "SHORT" and ema50 < ema200:
            score += 20
            reasons.append("Trend Bearish")

        # structure
        if direction == "LONG" and htf_struct == "BULLISH":
            score += 15
        if direction == "SHORT" and htf_struct == "BEARISH":
            score += 15

        # liquidity sweep
        if sweep == "BULLISH" and direction == "LONG":
            score += 15
            reasons.append("Liquidity Sweep")
        if sweep == "BEARISH" and direction == "SHORT":
            score += 15
            reasons.append("Liquidity Sweep")

        # CHOCH
        if choch:
            score += 10
            reasons.append("CHOCH")

        # RSI
        if direction == "LONG" and rsi < 40:
            score += 10
        if direction == "SHORT" and rsi > 60:
            score += 10

        # session
        if sess in ["LONDON", "NEWYORK"]:
            score += 10

        if score < MIN_SCORE:
            continue

        sl = price - atr * 2 if direction == "LONG" else price + atr * 2
        tp1 = price + atr * 3 if direction == "LONG" else price - atr * 3
        tp2 = price + atr * 5 if direction == "LONG" else price - atr * 5

        rr = abs(tp2 - price) / abs(sl - price)

        results.append({
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "price": price,
            "sl": round(sl, 6),
            "tp1": round(tp1, 6),
            "tp2": round(tp2, 6),
            "rr": round(rr, 2),
            "rsi": rsi,
            "reasons": reasons,
            "session": sess
        })

    return max(results, key=lambda x: x["score"]) if results else None

# ───────────────────────── TELEGRAM ─────────────────────────
def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def format(sig):
    emoji = "🟢" if sig["direction"] == "LONG" else "🔴"

    msg = f"""{emoji} SIGNAL
────────────────
{sig['symbol']} | {sig['direction']}
Score: {sig['score']}/100

Entry: {sig['price']}
SL: {sig['sl']}
TP1: {sig['tp1']}
TP2: {sig['tp2']}
RR: 1:{sig['rr']}

RSI: {sig['rsi']:.0f}
Session: {sig['session']}
────────────────
"""
    return msg

# ───────────────────────── MAIN ─────────────────────────
def main():
    print("Bot Running...")

    for s in SYMBOLS:
        try:
            sig = analyze(s)
            if sig:
                send(format(sig))
                print("SIGNAL", s, sig["score"])
            else:
                print("skip", s)
            time.sleep(1)
        except:
            continue

    send(f"Scan done {datetime.now()}")

if __name__ == "__main__":
    main()
