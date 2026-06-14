#!/usr/bin/env python3

import os
import requests
import time
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOLS = ["BTC-USDT", "ETH-USDT", "BNB-USDT", "XRP-USDT", "SOL-USDT",
           "ADA-USDT", "DOGE-USDT", "TRX-USDT", "AVAX-USDT", "SHIB-USDT",
           "DOT-USDT", "LINK-USDT", "MATIC-USDT", "LTC-USDT", "UNI-USDT",
           "ATOM-USDT", "XLM-USDT", "ETC-USDT", "APT-USDT", "NEAR-USDT"]

HTF = "1hour"
ITF = "15min"
LTF = "5min"
MIN_SCORE = 45

BASE_URL = "https://api.kucoin.com"

def get_klines(symbol, interval, limit=100):
    url = f"{BASE_URL}/api/v1/market/candles"
    params = {"symbol": symbol, "type": interval}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        candles = []
        for d in reversed(data.get("data", [])[:limit]):
            candles.append({
                "open":   float(d[1]),
                "close":  float(d[2]),
                "high":   float(d[3]),
                "low":    float(d[4]),
                "volume": float(d[5]),
            })
        return candles
    except Exception as e:
        print(f"[ERROR] {symbol}: {e}")
        return []

def get_price(symbol):
    try:
        r = requests.get(f"{BASE_URL}/api/v1/market/stats", params={"symbol": symbol}, timeout=5)
        data = r.json().get("data", {})
        return float(data.get("last", 0)), float(data.get("changeRate", 0)) * 100
    except:
        return 0, 0

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
        bos = "BULLISH_BOS" if candles[-1]["close"] > highs[-1] else None
        return "BULLISH", bos
    elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        bos = "BEARISH_BOS" if candles[-1]["close"] < lows[-1] else None
        return "BEARISH", bos
    return "NEUTRAL", None

def find_ob(candles):
    bull_obs, bear_obs = [], []
    for i in range(2, len(candles)-2):
        c, nc = candles[i], candles[i+1]
        body = abs(c["close"] - c["open"])
        next_body = abs(nc["close"] - nc["open"])
        if c["close"] < c["open"] and nc["close"] > nc["open"] and next_body > body * 1.5:
            bull_obs.append({"top": c["open"], "bottom": c["low"]})
        if c["close"] > c["open"] and nc["close"] < nc["open"] and next_body > body * 1.5:
            bear_obs.append({"top": c["high"], "bottom": c["open"]})
    return bull_obs[-3:], bear_obs[-3:]

def find_fvg(candles):
    bull_fvg, bear_fvg = [], []
    for i in range(len(candles)-2):
        if candles[i+2]["low"] > candles[i]["high"]:
            bull_fvg.append({"top": candles[i+2]["low"], "bottom": candles[i]["high"]})
        if candles[i+2]["high"] < candles[i]["low"]:
            bear_fvg.append({"top": candles[i]["low"], "bottom": candles[i+2]["high"]})
    return bull_fvg[-3:], bear_fvg[-3:]

def calc_rsi(candles, p=14):
    closes = [c["close"] for c in candles]
    if len(closes) < p+1:
        return 50
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-p:]) / p
    al = sum(losses[-p:]) / p
    return 100 - (100/(1+ag/al)) if al != 0 else 100

def calc_atr(candles, p=14):
    trs = [max(c["high"]-c["low"],
               abs(c["high"]-candles[i-1]["close"]),
               abs(c["low"]-candles[i-1]["close"]))
           for i, c in enumerate(candles) if i > 0]
    return sum(trs[-p:]) / min(p, len(trs)) if trs else 0

def detect_session():
    h = datetime.now(timezone.utc).hour
    if 7 <= h < 12:
        return "LONDON"
    elif 12 <= h < 20:
        return "NEWYORK"
    return "ASIAN"

def analyze(symbol):
    htf = get_klines(symbol, HTF, 100)
    itf = get_klines(symbol, ITF, 100)
    ltf = get_klines(symbol, LTF, 50)
    if not htf or not itf or not ltf:
        return None

    price = ltf[-1]["close"]
    atr = calc_atr(ltf)
    rsi = calc_rsi(ltf)
    session = detect_session()
    htf_struct, _ = detect_structure(htf)
    ltf_struct, ltf_bos = detect_structure(ltf)
    bull_ob, bear_ob = find_ob(itf)
    bull_fvg, bear_fvg = find_fvg(itf)

    results = []
    for direction in ["LONG", "SHORT"]:
        score = 0
        reasons = []

        # ساختار HTF
        if direction == "LONG" and htf_struct == "BULLISH":
            score += 25
            reasons.append("HTF صعودی")
        elif direction == "SHORT" and htf_struct == "BEARISH":
            score += 25
            reasons.append("HTF نزولی")

        # BOS
        if direction == "LONG" and ltf_bos == "BULLISH_BOS":
            score += 15
            reasons.append("BOS صعودی")
        elif direction == "SHORT" and ltf_bos == "BEARISH_BOS":
            score += 15
            reasons.append("BOS نزولی")

        # Order Block
        if direction == "LONG":
            for ob in reversed(bull_ob):
                if ob["bottom"] <= price <= ob["top"] * 1.01:
                    score += 20
                    reasons.append(f"Bullish OB")
                    break
        else:
            for ob in reversed(bear_ob):
                if ob["bottom"] * 0.99 <= price <= ob["top"]:
                    score += 20
                    reasons.append(f"Bearish OB")
                    break

        # FVG
        if direction == "LONG":
            for fvg in reversed(bull_fvg):
                if fvg["bottom"] <= price <= fvg["top"]:
                    score += 15
                    reasons.append("Bullish FVG")
                    break
        else:
            for fvg in reversed(bear_fvg):
                if fvg["bottom"] <= price <= fvg["top"]:
                    score += 15
                    reasons.append("Bearish FVG")
                    break

        # RSI
        if direction == "LONG" and rsi < 35:
            score += 15
            reasons.append(f"RSI اشباع فروش ({rsi:.0f})")
        elif direction == "LONG" and rsi < 50:
            score += 8
            reasons.append(f"RSI مناسب ({rsi:.0f})")
        elif direction == "SHORT" and rsi > 65:
            score += 15
            reasons.append(f"RSI اشباع خرید ({rsi:.0f})")
        elif direction == "SHORT" and rsi > 50:
            score += 8
            reasons.append(f"RSI مناسب ({rsi:.0f})")

        # سشن
        if session in ["LONDON", "NEWYORK"]:
            score += 10
            reasons.append(f"سشن {session}")

        if score >= MIN_SCORE:
            if direction == "LONG":
                sl = round(price - atr * 1.5, 6)
                tp1 = round(price + atr * 1.5, 6)
                tp2 = round(price + atr * 3.0, 6)
            else:
                sl = round(price + atr * 1.5, 6)
                tp1 = round(price - atr * 1.5, 6)
                tp2 = round(price - atr * 3.0, 6)

            rr = round(abs(tp2 - price) / abs(sl - price), 1) if abs(sl - price) > 0 else 0

            results.append({
                "symbol": symbol,
                "direction": direction,
                "score": score,
                "price": price,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "rr": rr,
                "rsi": rsi,
                "reasons": reasons,
                "session": session
            })

    if not results:
        return None
    return max(results, key=lambda x: x["score"])

def format_msg(s):
    emoji = "🟢" if s["direction"] == "LONG" else "🔴"
    dir_fa = "خرید (LONG)" if s["direction"] == "LONG" else "فروش (SHORT)"
    quality = "💎 عالی" if s["score"] >= 70 else ("✨ خوب" if s["score"] >= 55 else "⚡ متوسط")
    symbol_clean = s["symbol"].replace("-", "")

    msg = f"""{emoji} سیگنال اسکلپ SMC
{'─'*20}
🪙 {symbol_clean} | {dir_fa}
📊 کیفیت: {quality} ({s['score']}/100)
{'─'*20}
💰 قیمت ورود: {s['price']}
🔴 استاپ لاس: {s['sl']}
🎯 تیک پروفیت ۱: {s['tp1']}
🎯 تیک پروفیت ۲: {s['tp2']}
📐 ریسک به ریوارد: 1:{s['rr']}
{'─'*20}
📋 تأییدیه‌ها:"""
    for r in s["reasons"]:
        msg += f"\n• {r}"
    msg += f"\n{'─'*20}"
    msg += f"\n📊 RSI: {s['rsi']:.0f} | ⏰ {s['session']}"
    msg += f"\n🕐 {datetime.now().strftime('%H:%M')}"
    msg += f"\n⚠️ صرفاً آموزشی - ریسک با خودت"
    return msg

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"[TG ERROR] {e}")

def main():
    print("SMC Bot Starting...")
    if not TELEGRAM_TOKEN:
        return

    found = 0
    for symbol in SYMBOLS:
        print(f"  {symbol}...", end=" ")
        try:
            sig = analyze(symbol)
            if sig:
                send_telegram(format_msg(sig))
                found += 1
                print(f"SIGNAL {sig['direction']} {sig['score']}")
            else:
                print("skip")
            time.sleep(1)
        except Exception as e:
            print(f"ERR: {e}")
            time.sleep(1)

    if found == 0:
        send_telegram(f"🔍 اسکن {len(SYMBOLS)} ارز تموم شد\n❌ سیگنال مناسب یافت نشد\n🕐 {datetime.now().strftime('%H:%M')}")
    print(f"Done! {found} signals")

if __name__ == "__main__":
    main()
