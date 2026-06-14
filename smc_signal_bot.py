#!/usr/bin/env python3

import os
import requests
import time
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
HTF = "1h"
ITF = "15m"
LTF = "5m"
MIN_SCORE = 65
CHECK_INTERVAL_MINUTES = 15

BASE_URL = "https://api.binance.com/api/v3"

def get_klines(symbol, interval, limit=100):
    url = f"{BASE_URL}/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        candles = []
        for d in data:
            candles.append({
                "open_time": d[0],
                "open":  float(d[1]),
                "high":  float(d[2]),
                "low":   float(d[3]),
                "close": float(d[4]),
                "volume":float(d[5]),
            })
        return candles
    except Exception as e:
        print(f"[ERROR] klines {symbol} {interval}: {e}")
        return []

def get_ticker(symbol):
    try:
        r = requests.get(f"{BASE_URL}/ticker/24hr", params={"symbol": symbol}, timeout=5)
        return r.json()
    except:
        return {}

def find_swing_points(candles, lookback=3):
    highs = []
    lows = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        is_swing_high = all(
            candles[i]["high"] > candles[j]["high"]
            for j in range(i - lookback, i + lookback + 1) if j != i
        )
        is_swing_low = all(
            candles[i]["low"] < candles[j]["low"]
            for j in range(i - lookback, i + lookback + 1) if j != i
        )
        if is_swing_high:
            highs.append({"index": i, "price": candles[i]["high"]})
        if is_swing_low:
            lows.append({"index": i, "price": candles[i]["low"]})
    return highs, lows

def detect_market_structure(candles):
    highs, lows = find_swing_points(candles)
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", None, None
    last_hh = highs[-1]["price"]
    prev_hh = highs[-2]["price"]
    last_ll = lows[-1]["price"]
    prev_ll = lows[-2]["price"]
    bos = None
    choch = None
    if last_hh > prev_hh and last_ll > prev_ll:
        structure = "BULLISH"
        if candles[-1]["close"] > last_hh:
            bos = "BULLISH_BOS"
    elif last_hh < prev_hh and last_ll < prev_ll:
        structure = "BEARISH"
        if candles[-1]["close"] < last_ll:
            bos = "BEARISH_BOS"
    else:
        structure = "NEUTRAL"
    if structure == "BULLISH" and last_ll < prev_ll:
        choch = "BEARISH_CHoCH"
    elif structure == "BEARISH" and last_hh > prev_hh:
        choch = "BULLISH_CHoCH"
    return structure, bos, choch

def find_order_blocks(candles):
    obs = []
    for i in range(2, len(candles) - 2):
        c = candles[i]
        next_c = candles[i + 1]
        body_size = abs(c["close"] - c["open"])
        next_move = abs(next_c["close"] - next_c["open"])
        if (c["close"] < c["open"] and next_c["close"] > next_c["open"] and next_move > body_size * 1.5):
            obs.append({"type": "BULLISH_OB", "top": c["open"], "bottom": c["low"],
                        "mid": (c["open"] + c["low"]) / 2, "index": i,
                        "strength": next_move / body_size if body_size > 0 else 1})
        if (c["close"] > c["open"] and next_c["close"] < next_c["open"] and next_move > body_size * 1.5):
            obs.append({"type": "BEARISH_OB", "top": c["high"], "bottom": c["open"],
                        "mid": (c["high"] + c["open"]) / 2, "index": i,
                        "strength": next_move / body_size if body_size > 0 else 1})
    return obs[-5:] if obs else []

def find_fvg(candles):
    fvgs = []
    for i in range(len(candles) - 2):
        c1 = candles[i]
        c3 = candles[i + 2]
        if c3["low"] > c1["high"]:
            fvgs.append({"type": "BULLISH_FVG", "top": c3["low"], "bottom": c1["high"],
                         "mid": (c3["low"] + c1["high"]) / 2, "size": c3["low"] - c1["high"]})
        if c3["high"] < c1["low"]:
            fvgs.append({"type": "BEARISH_FVG", "top": c1["low"], "bottom": c3["high"],
                         "mid": (c1["low"] + c3["high"]) / 2, "size": c1["low"] - c3["high"]})
    return fvgs[-6:] if fvgs else []

def find_liquidity_zones(candles, tolerance=0.002):
    highs = [c["high"] for c in candles[-30:]]
    lows = [c["low"] for c in candles[-30:]]
    eqh_zones = []
    eql_zones = []
    for i in range(len(highs)):
        for j in range(i + 2, len(highs)):
            diff = abs(highs[i] - highs[j]) / highs[i]
            if diff < tolerance:
                level = (highs[i] + highs[j]) / 2
                if level not in [z["level"] for z in eqh_zones]:
                    eqh_zones.append({"level": level, "type": "BSL"})
    for i in range(len(lows)):
        for j in range(i + 2, len(lows)):
            if lows[i] == 0:
                continue
            diff = abs(lows[i] - lows[j]) / lows[i]
            if diff < tolerance:
                level = (lows[i] + lows[j]) / 2
                if level not in [z["level"] for z in eql_zones]:
                    eql_zones.append({"level": level, "type": "SSL"})
    return eqh_zones[-3:], eql_zones[-3:]

def detect_amd_phase(candles):
    last_20 = candles[-20:]
    if not last_20:
        return "UNKNOWN"
    highs = [c["high"] for c in last_20]
    lows = [c["low"] for c in last_20]
    closes = [c["close"] for c in last_20]
    price_range = max(highs) - min(lows)
    avg_range = price_range / len(last_20)
    recent_range = max(highs[-5:]) - min(lows[-5:])
    if recent_range < avg_range * 0.7:
        return "ACCUMULATION"
    elif closes[-1] > closes[-3] and recent_range > avg_range * 1.5:
        return "MANIPULATION_UP"
    elif closes[-1] < closes[-3] and recent_range > avg_range * 1.5:
        return "MANIPULATION_DOWN"
    elif abs(closes[-1] - closes[-5]) > price_range * 0.3:
        return "DISTRIBUTION"
    return "TRANSITION"

def detect_session():
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 7:
        return "ASIAN", "آسیا"
    elif 7 <= hour < 12:
        return "LONDON", "لندن"
    elif 12 <= hour < 20:
        return "NEWYORK", "نیویورک"
    else:
        return "OVERLAP", "اورلپ"

def calculate_rsi(candles, period=14):
    closes = [c["close"] for c in candles]
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if not trs:
        return 0
    return sum(trs[-period:]) / min(period, len(trs))

def score_signal(symbol, direction):
    score = 0
    reasons = []
    warnings = []
    htf_candles = get_klines(symbol, HTF, 100)
    itf_candles = get_klines(symbol, ITF, 100)
    ltf_candles = get_klines(symbol, LTF, 50)
    if not htf_candles or not itf_candles or not ltf_candles:
        return 0, [], [], {}
    price = ltf_candles[-1]["close"]
    atr = calculate_atr(ltf_candles)
    rsi_ltf = calculate_rsi(ltf_candles)
    htf_struct, htf_bos, htf_choch = detect_market_structure(htf_candles)
    if direction == "LONG" and htf_struct == "BULLISH":
        score += 25
        reasons.append("HTF ساختار صعودی")
    elif direction == "SHORT" and htf_struct == "BEARISH":
        score += 25
        reasons.append("HTF ساختار نزولی")
    else:
        warnings.append("خلاف روند HTF")
    ltf_struct, ltf_bos, ltf_choch = detect_market_structure(ltf_candles)
    if direction == "LONG" and ltf_choch == "BULLISH_CHoCH":
        score += 15
        reasons.append("CHoCH صعودی در LTF")
    elif direction == "SHORT" and ltf_choch == "BEARISH_CHoCH":
        score += 15
        reasons.append("CHoCH نزولی در LTF")
    elif direction == "LONG" and ltf_bos == "BULLISH_BOS":
        score += 10
        reasons.append("BOS صعودی در LTF")
    elif direction == "SHORT" and ltf_bos == "BEARISH_BOS":
        score += 10
        reasons.append("BOS نزولی در LTF")
    itf_obs = find_order_blocks(itf_candles)
    ob_hit = False
    active_ob = None
    for ob in reversed(itf_obs):
        if direction == "LONG" and ob["type"] == "BULLISH_OB":
            if ob["bottom"] <= price <= ob["top"] * 1.01:
                score += 15
                reasons.append(f"روی Bullish OB")
                ob_hit = True
                active_ob = ob
                break
        elif direction == "SHORT" and ob["type"] == "BEARISH_OB":
            if ob["bottom"] * 0.99 <= price <= ob["top"]:
                score += 15
                reasons.append(f"روی Bearish OB")
                ob_hit = True
                active_ob = ob
                break
    if not ob_hit:
        warnings.append("خارج از Order Block")
    itf_fvgs = find_fvg(itf_candles)
    for fvg in reversed(itf_fvgs):
        if direction == "LONG" and fvg["type"] == "BULLISH_FVG":
            if fvg["bottom"] <= price <= fvg["top"]:
                score += 10
                reasons.append("داخل Bullish FVG")
                break
        elif direction == "SHORT" and fvg["type"] == "BEARISH_FVG":
            if fvg["bottom"] <= price <= fvg["top"]:
                score += 10
                reasons.append("داخل Bearish FVG")
                break
    eqh, eql = find_liquidity_zones(itf_candles)
    for zone in eqh:
        if direction == "SHORT" and abs(price - zone["level"]) / price < 0.005:
            score += 10
            reasons.append("نزدیک BSL (EQH)")
    for zone in eql:
        if direction == "LONG" and abs(price - zone["level"]) / price < 0.005:
            score += 10
            reasons.append("نزدیک SSL (EQL)")
    if direction == "LONG" and rsi_ltf < 30:
        score += 10
        reasons.append(f"RSI اشباع فروش ({rsi_ltf:.1f})")
    elif direction == "LONG" and 30 <= rsi_ltf <= 55:
        score += 7
        reasons.append(f"RSI مناسب ({rsi_ltf:.1f})")
    elif direction == "SHORT" and rsi_ltf > 70:
        score += 10
        reasons.append(f"RSI اشباع خرید ({rsi_ltf:.1f})")
    elif direction == "SHORT" and 45 <= rsi_ltf <= 75:
        score += 7
        reasons.append(f"RSI مناسب ({rsi_ltf:.1f})")
    avg_vol = sum(c["volume"] for c in ltf_candles[-20:]) / 20
    last_vol = ltf_candles[-1]["volume"]
    last_body = abs(ltf_candles[-1]["close"] - ltf_candles[-1]["open"])
    last_range = ltf_candles[-1]["high"] - ltf_candles[-1]["low"]
    wick_ratio = (last_range - last_body) / last_range if last_range > 0 else 0
    if last_vol > avg_vol * 1.3 and wick_ratio < 0.4:
        score += 8
        reasons.append("حجم بالا + مشارکت نهادی")
    session, session_desc = detect_session()
    if session in ["LONDON", "NEWYORK"]:
        score += 5
        reasons.append(f"سشن {session_desc}")
    extras = {
        "price": price, "atr": atr, "rsi": rsi_ltf,
        "session": session, "amd_phase": detect_amd_phase(ltf_candles),
        "htf_structure": htf_struct, "ltf_structure": ltf_struct,
        "active_ob": active_ob, "eqh": eqh, "eql": eql,
    }
    if direction == "LONG":
        extras["sl"] = price - (atr * 1.5)
        extras["tp1"] = price + (atr * 1.5)
        extras["tp2"] = price + (atr * 2.5)
        extras["tp3"] = price + (atr * 4.0)
        if eqh:
            extras["tp_liquidity"] = eqh[0]["level"]
    else:
        extras["sl"] = price + (atr * 1.5)
        extras["tp1"] = price - (atr * 1.5)
        extras["tp2"] = price - (atr * 2.5)
        extras["tp3"] = price - (atr * 4.0)
        if eql:
            extras["tp_liquidity"] = eql[0]["level"]
    rr = abs(extras["tp2"] - price) / abs(extras["sl"] - price) if abs(extras["sl"] - price) > 0 else 0
    extras["rr"] = rr
    return score, reasons, warnings, extras

def analyze_symbol(symbol):
    ltf_candles = get_klines(symbol, LTF, 50)
    itf_candles = get_klines(symbol, ITF, 100)
    if not ltf_candles or not itf_candles:
        return None
    price = ltf_candles[-1]["close"]
    _, _, ltf_choch = detect_market_structure(ltf_candles)
    _, _, itf_choch = detect_market_structure(itf_candles)
    itf_obs = find_order_blocks(itf_candles)
    itf_fvgs = find_fvg(itf_candles)
    signals = []
    for direction in ["LONG", "SHORT"]:
        choch_signal = (
            (direction == "LONG" and ltf_choch == "BULLISH_CHoCH") or
            (direction == "SHORT" and ltf_choch == "BEARISH_CHoCH") or
            (direction == "LONG" and itf_choch == "BULLISH_CHoCH") or
            (direction == "SHORT" and itf_choch == "BEARISH_CHoCH")
        )
        ob_exists = any(
            (direction == "LONG" and ob["type"] == "BULLISH_OB" and ob["bottom"] <= price <= ob["top"] * 1.02)
            or (direction == "SHORT" and ob["type"] == "BEARISH_OB" and ob["bottom"] * 0.98 <= price <= ob["top"])
            for ob in itf_obs
        )
        fvg_exists = any(
            (direction == "LONG" and fvg["type"] == "BULLISH_FVG" and fvg["bottom"] <= price <= fvg["top"])
            or (direction == "SHORT" and fvg["type"] == "BEARISH_FVG" and fvg["bottom"] <= price <= fvg["top"])
            for fvg in itf_fvgs
        )
        if choch_signal or ob_exists or fvg_exists:
            score, reasons, warnings, extras = score_signal(symbol, direction)
            if score >= MIN_SCORE:
                signals.append({"symbol": symbol, "direction": direction,
                                 "score": score, "reasons": reasons,
                                 "warnings": warnings, "extras": extras})
    if signals:
        return max(signals, key=lambda x: x["score"])
    return None

def format_signal_message(sig):
    e = sig["extras"]
    d = sig["direction"]
    symbol = sig["symbol"]
    score = sig["score"]
    price = e["price"]
    emoji = "🟢" if d == "LONG" else "🔴"
    dir_fa = "خرید LONG" if d == "LONG" else "فروش SHORT"
    quality = "💎 عالی" if score >= 85 else ("✨ خوب" if score >= 70 else "⚡ متوسط")
    struct_map = {"BULLISH": "📈 صعودی", "BEARISH": "📉 نزولی", "NEUTRAL": "↔️ خنثی"}
    msg = f"""{emoji} سیگنال اسکلپ SMC
🪙 {symbol} | {dir_fa}
💰 قیمت: {price:.6f}
📊 کیفیت: {quality} ({score}/100)
─────────────────
🏗 HTF: {struct_map.get(e['htf_structure'], '?')}
🏗 LTF: {struct_map.get(e['ltf_structure'], '?')}
📊 RSI: {e['rsi']:.1f}
🔄 فاز: {e['amd_phase']}
─────────────────
🔴 SL: {e['sl']:.6f}
🎯 TP1: {e['tp1']:.6f}
🎯 TP2: {e['tp2']:.6f}
🎯 TP3: {e['tp3']:.6f}
📐 R:R = 1:{e['rr']:.1f}"""
    if "tp_liquidity" in e:
        msg += f"\n💧 نقدینگی: {e['tp_liquidity']:.6f}"
    msg += "\n─────────────────\n✅ تأییدیه‌ها:"
    for r in sig["reasons"][:5]:
        msg += f"\n• {r}"
    if sig["warnings"]:
        msg += "\n⚠️ هشدار:"
        for w in sig["warnings"][:2]:
            msg += f"\n• {w}"
    msg += f"\n─────────────────"
    msg += f"\n🕐 {datetime.now().strftime('%H:%M')} | ⚠️ صرفاً آموزشی"
    return msg

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        return False

def send_market_summary():
    session, session_desc = detect_session()
    btc = get_klines("BTCUSDT", "1h", 50)
    if not btc:
        return
    btc_struct, _, _ = detect_market_structure(btc)
    btc_rsi = calculate_rsi(btc)
    btc_price = btc[-1]["close"]
    ticker = get_ticker("BTCUSDT")
    change_24h = float(ticker.get("priceChangePercent", 0))
    struct_map = {"BULLISH": "📈 صعودی", "BEARISH": "📉 نزولی", "NEUTRAL": "↔️ خنثی"}
    msg = f"""🌐 خلاصه بازار SMC
🕐 {datetime.now().strftime('%H:%M')} UTC | {session_desc}
─────────────────
BTC: ${btc_price:,.2f} ({change_24h:+.2f}%)
ساختار: {struct_map.get(btc_struct,'?')}
RSI: {btc_rsi:.1f}
─────────────────
🔎 اسکن {len(SYMBOLS)} ارز | حداقل امتیاز: {MIN_SCORE}"""
    send_telegram(msg)

def main():
    print("SMC Signal Bot Starting...")
    if not TELEGRAM_TOKEN:
        print("خطا: TELEGRAM_TOKEN تنظیم نشده!")
        return
    send_telegram("🤖 SMC Bot شروع به کار کرد\n✅ اتصال برقرار\n📊 در حال اسکن بازار...")
    print("ربات شروع شد!")
    cycle = 0
    while True:
        cycle += 1
        print(f"\n[Cycle {cycle}] {datetime.now().strftime('%H:%M:%S')}")
        if cycle % 4 == 1:
            send_market_summary()
        for symbol in SYMBOLS:
            print(f"  {symbol}...", end=" ")
            try:
                sig = analyze_symbol(symbol)
                if sig:
                    msg = format_signal_message(sig)
                    send_telegram(msg)
                    print(f"SIGNAL! {sig['direction']} score:{sig['score']}")
                else:
                    print("no signal")
                time.sleep(1.5)
            except Exception as ex:
                print(f"ERROR: {ex}")
                time.sleep(2)
        print(f"Next scan in {CHECK_INTERVAL_MINUTES} min")
        time.sleep(CHECK_INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()
