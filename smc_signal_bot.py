#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║     SMC + Price Action Scalp Signal Bot                  ║
║     Smart Money Concepts | Order Blocks | FVG | CHoCH    ║
║     Telegram Notifications | Termux Compatible           ║
╚══════════════════════════════════════════════════════════╝
"""

import requests
import time
import json
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════
#  ⚙️  تنظیمات - اینجا رو پر کن
# ═══════════════════════════════════════════════════════════
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"

# جفت‌ارزهایی که می‌خوای آنالیز بشن
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# تایم‌فریم‌ها (برای اسکلپ)
# HTF = 1h, ITF = 15m, LTF = 5m
HTF = "1h"
ITF = "15m"
LTF = "5m"

# فیلتر کیفیت سیگنال (حداقل امتیاز از 100)
MIN_SCORE = 65

# تعداد دقیقه بین هر چک
CHECK_INTERVAL_MINUTES = 15

# ═══════════════════════════════════════════════════════════
#  📡  دریافت داده از Binance (بدون API Key)
# ═══════════════════════════════════════════════════════════
BASE_URL = "https://api.binance.com/api/v3"

def get_klines(symbol, interval, limit=100):
    """دریافت کندل‌ها از بایننس"""
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
    """قیمت لحظه‌ای"""
    try:
        r = requests.get(f"{BASE_URL}/ticker/24hr", params={"symbol": symbol}, timeout=5)
        return r.json()
    except:
        return {}

# ═══════════════════════════════════════════════════════════
#  🧠  موتور SMC - تشخیص ساختار بازار
# ═══════════════════════════════════════════════════════════

def find_swing_points(candles, lookback=5):
    """
    تشخیص Swing High و Swing Low واقعی
    (از PDF: مرکز کندل باید بالاترین high یا پایین‌ترین low داشته باشه)
    """
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
            highs.append({"index": i, "price": candles[i]["high"], "candle": candles[i]})
        if is_swing_low:
            lows.append({"index": i, "price": candles[i]["low"], "candle": candles[i]})
    return highs, lows


def detect_market_structure(candles):
    """
    تشخیص ساختار بازار: HH/HL (صعودی) یا LH/LL (نزولی)
    همچنین تشخیص BOS و CHoCH
    """
    highs, lows = find_swing_points(candles, lookback=3)
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", None, None

    last_hh = highs[-1]["price"]
    prev_hh = highs[-2]["price"]
    last_ll = lows[-1]["price"]
    prev_ll = lows[-2]["price"]

    bos = None
    choch = None

    # ساختار صعودی: HH و HL
    if last_hh > prev_hh and last_ll > prev_ll:
        structure = "BULLISH"
        # BOS: شکستن سوئینگ هاي قبلی در جهت روند
        if candles[-1]["close"] > last_hh:
            bos = "BULLISH_BOS"
    # ساختار نزولی: LH و LL
    elif last_hh < prev_hh and last_ll < prev_ll:
        structure = "BEARISH"
        if candles[-1]["close"] < last_ll:
            bos = "BEARISH_BOS"
    else:
        structure = "NEUTRAL"

    # CHoCH: تغییر کاراکتر (برعکس شدن ساختار)
    # اگه ساختار صعودی بود ولی آخرین LL پایین‌تر از قبلی شکست
    if structure == "BULLISH" and last_ll < prev_ll:
        choch = "BEARISH_CHoCH"
    elif structure == "BEARISH" and last_hh > prev_hh:
        choch = "BULLISH_CHoCH"

    return structure, bos, choch


def find_order_blocks(candles):
    """
    تشخیص Order Block
    آخرین کندل قبل از یک حرکت قوی (Impulse Move) که باعث BOS شد
    - Bullish OB: آخرین کندل نزولی قبل از یک پامپ قوی
    - Bearish OB: آخرین کندل صعودی قبل از یک دامپ قوی
    """
    obs = []
    for i in range(2, len(candles) - 2):
        c = candles[i]
        next_c = candles[i + 1]
        prev_c = candles[i - 1]

        body_size = abs(c["close"] - c["open"])
        next_move = abs(next_c["close"] - next_c["open"])

        # Bullish OB: کندل نزولی + بعدش پامپ قوی
        if (c["close"] < c["open"] and
                next_c["close"] > next_c["open"] and
                next_move > body_size * 1.5):
            obs.append({
                "type": "BULLISH_OB",
                "top": c["open"],
                "bottom": c["low"],
                "mid": (c["open"] + c["low"]) / 2,
                "index": i,
                "strength": next_move / body_size if body_size > 0 else 1
            })

        # Bearish OB: کندل صعودی + بعدش دامپ قوی
        if (c["close"] > c["open"] and
                next_c["close"] < next_c["open"] and
                next_move > body_size * 1.5):
            obs.append({
                "type": "BEARISH_OB",
                "top": c["high"],
                "bottom": c["open"],
                "mid": (c["high"] + c["open"]) / 2,
                "index": i,
                "strength": next_move / body_size if body_size > 0 else 1
            })

    # فقط آخرین OBها رو برمیگردونیم (مهمترین)
    return obs[-5:] if obs else []


def find_fvg(candles):
    """
    تشخیص Fair Value Gap (Imbalance)
    از PDF: Low Volume + Large Body = Vacuum = FVG که باید پر بشه
    FVG: بین Low کندل i+2 و High کندل i یه فضا باشه
    """
    fvgs = []
    for i in range(len(candles) - 2):
        c1 = candles[i]
        c2 = candles[i + 1]  # کندل وسط (قوی)
        c3 = candles[i + 2]

        body_c2 = abs(c2["close"] - c2["open"])
        avg_body = sum(abs(candles[j]["close"] - candles[j]["open"]) for j in range(max(0, i-5), i)) / max(1, min(5, i))

        # فقط FVGهای مهم (کندل وسط بزرگ باشه)
        if avg_body > 0 and body_c2 < avg_body * 0.5:
            continue

        # Bullish FVG: Low کندل سوم > High کندل اول
        if c3["low"] > c1["high"]:
            gap_size = c3["low"] - c1["high"]
            fvgs.append({
                "type": "BULLISH_FVG",
                "top": c3["low"],
                "bottom": c1["high"],
                "mid": (c3["low"] + c1["high"]) / 2,
                "index": i + 1,
                "size": gap_size,
                "filled": False
            })

        # Bearish FVG: High کندل سوم < Low کندل اول
        if c3["high"] < c1["low"]:
            gap_size = c1["low"] - c3["high"]
            fvgs.append({
                "type": "BEARISH_FVG",
                "top": c1["low"],
                "bottom": c3["high"],
                "mid": (c1["low"] + c3["high"]) / 2,
                "index": i + 1,
                "size": gap_size,
                "filled": False
            })

    return fvgs[-6:] if fvgs else []


def find_liquidity_zones(candles, tolerance=0.002):
    """
    تشخیص مناطق نقدینگی (از PDF):
    - Equal Highs (EQH) = Buy-Side Liquidity
    - Equal Lows (EQL) = Sell-Side Liquidity
    """
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
                    eqh_zones.append({"level": level, "type": "BSL", "label": "Equal Highs (BSL)"})

    for i in range(len(lows)):
        for j in range(i + 2, len(lows)):
            if lows[i] == 0:
                continue
            diff = abs(lows[i] - lows[j]) / lows[i]
            if diff < tolerance:
                level = (lows[i] + lows[j]) / 2
                if level not in [z["level"] for z in eql_zones]:
                    eql_zones.append({"level": level, "type": "SSL", "label": "Equal Lows (SSL)"})

    return eqh_zones[-3:], eql_zones[-3:]


def detect_amd_phase(candles):
    """
    تشخیص فاز AMD (Accumulation, Manipulation, Distribution)
    از PDF: Power of Three (PO3) / Wyckoff
    """
    last_20 = candles[-20:]
    if not last_20:
        return "UNKNOWN"

    highs = [c["high"] for c in last_20]
    lows = [c["low"] for c in last_20]
    closes = [c["close"] for c in last_20]

    price_range = max(highs) - min(lows)
    avg_range = price_range / len(last_20)

    # محاسبه نوسان
    recent_range = max(highs[-5:]) - min(lows[-5:])
    early_range  = max(highs[:5]) - min(lows[:5])

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
    """تشخیص سشن فعال (از PDF)"""
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 7:
        return "ASIAN", "⚡ تجمع/توزیع الگوریتمی"
    elif 7 <= hour < 12:
        return "LONDON", "🔥 سشن لندن - دستکاری نهادی"
    elif 12 <= hour < 20:
        return "NEWYORK", "💹 سشن نیویورک - بالاترین نوسان"
    else:
        return "OVERLAP", "🌐 اورلپ"


def calculate_ema(candles, period):
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return closes[-1]
    k = 2 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def calculate_rsi(candles, period=14):
    closes = [c["close"] for c in candles]
    if len(closes) < period + 1:
        return 50
    gains = []
    losses = []
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


# ═══════════════════════════════════════════════════════════
#  🎯  موتور امتیازدهی سیگنال (Multi-Confirmation System)
# ═══════════════════════════════════════════════════════════

def score_signal(symbol, direction):
    """
    سیستم امتیازدهی چندلایه برای فیلتر سیگنال‌های ضعیف
    امتیاز 0-100 | MIN_SCORE برای ارسال سیگنال
    """
    score = 0
    reasons = []
    warnings = []

    # دریافت داده تمام تایم‌فریم‌ها
    htf_candles = get_klines(symbol, HTF, 100)
    itf_candles = get_klines(symbol, ITF, 100)
    ltf_candles = get_klines(symbol, LTF, 50)

    if not htf_candles or not itf_candles or not ltf_candles:
        return 0, [], [], {}

    price = ltf_candles[-1]["close"]
    atr = calculate_atr(ltf_candles)
    rsi_ltf = calculate_rsi(ltf_candles)
    rsi_itf = calculate_rsi(itf_candles)

    # ─── لایه ۱: همسویی ساختار HTF (۲۵ امتیاز) ───────────────
    htf_struct, htf_bos, htf_choch = detect_market_structure(htf_candles)
    if direction == "LONG" and htf_struct == "BULLISH":
        score += 25
        reasons.append("✅ HTF ساختار صعودی (HH/HL)")
    elif direction == "SHORT" and htf_struct == "BEARISH":
        score += 25
        reasons.append("✅ HTF ساختار نزولی (LH/LL)")
    elif htf_struct == "NEUTRAL":
        warnings.append("⚠️ HTF بی‌روند - احتیاط!")
    else:
        warnings.append("❌ معامله خلاف روند HTF")

    # ─── لایه ۲: CHoCH در LTF (15 امتیاز) ───────────────────
    ltf_struct, ltf_bos, ltf_choch = detect_market_structure(ltf_candles)
    if direction == "LONG" and ltf_choch == "BULLISH_CHoCH":
        score += 15
        reasons.append("✅ CHoCH صعودی در LTF - تغییر کاراکتر")
    elif direction == "SHORT" and ltf_choch == "BEARISH_CHoCH":
        score += 15
        reasons.append("✅ CHoCH نزولی در LTF - تغییر کاراکتر")
    elif direction == "LONG" and ltf_bos == "BULLISH_BOS":
        score += 10
        reasons.append("✅ BOS صعودی در LTF")
    elif direction == "SHORT" and ltf_bos == "BEARISH_BOS":
        score += 10
        reasons.append("✅ BOS نزولی در LTF")

    # ─── لایه ۳: Order Block (15 امتیاز) ─────────────────────
    itf_obs = find_order_blocks(itf_candles)
    ob_hit = False
    active_ob = None
    for ob in reversed(itf_obs):
        if direction == "LONG" and ob["type"] == "BULLISH_OB":
            if ob["bottom"] <= price <= ob["top"] * 1.01:
                score += 15
                reasons.append(f"✅ قیمت روی Bullish OB ({ob['bottom']:.4f} - {ob['top']:.4f})")
                ob_hit = True
                active_ob = ob
                break
        elif direction == "SHORT" and ob["type"] == "BEARISH_OB":
            if ob["bottom"] * 0.99 <= price <= ob["top"]:
                score += 15
                reasons.append(f"✅ قیمت روی Bearish OB ({ob['bottom']:.4f} - {ob['top']:.4f})")
                ob_hit = True
                active_ob = ob
                break

    if not ob_hit:
        warnings.append("⚠️ خارج از Order Block")

    # ─── لایه ۴: Fair Value Gap (10 امتیاز) ─────────────────
    itf_fvgs = find_fvg(itf_candles)
    for fvg in reversed(itf_fvgs):
        if direction == "LONG" and fvg["type"] == "BULLISH_FVG":
            if fvg["bottom"] <= price <= fvg["top"]:
                score += 10
                reasons.append(f"✅ داخل Bullish FVG ({fvg['bottom']:.4f} - {fvg['top']:.4f})")
                break
        elif direction == "SHORT" and fvg["type"] == "BEARISH_FVG":
            if fvg["bottom"] <= price <= fvg["top"]:
                score += 10
                reasons.append(f"✅ داخل Bearish FVG ({fvg['bottom']:.4f} - {fvg['top']:.4f})")
                break

    # ─── لایه ۵: نقدینگی (10 امتیاز) ────────────────────────
    eqh, eql = find_liquidity_zones(itf_candles)
    for zone in eqh:
        if direction == "SHORT" and abs(price - zone["level"]) / price < 0.005:
            score += 10
            reasons.append(f"✅ نزدیک BSL (EQH) - هدف نقدینگی فروش: {zone['level']:.4f}")
    for zone in eql:
        if direction == "LONG" and abs(price - zone["level"]) / price < 0.005:
            score += 10
            reasons.append(f"✅ نزدیک SSL (EQL) - هدف نقدینگی خرید: {zone['level']:.4f}")

    # ─── لایه ۶: RSI (10 امتیاز) ─────────────────────────────
    if direction == "LONG" and 30 <= rsi_ltf <= 55:
        score += 7
        reasons.append(f"✅ RSI در ناحیه مناسب خرید ({rsi_ltf:.1f})")
    elif direction == "SHORT" and 45 <= rsi_ltf <= 75:
        score += 7
        reasons.append(f"✅ RSI در ناحیه مناسب فروش ({rsi_ltf:.1f})")
    elif direction == "LONG" and rsi_ltf < 30:
        score += 10
        reasons.append(f"✅ RSI اشباع فروش ({rsi_ltf:.1f}) - برگشت قوی‌تر")
    elif direction == "SHORT" and rsi_ltf > 70:
        score += 10
        reasons.append(f"✅ RSI اشباع خرید ({rsi_ltf:.1f}) - برگشت قوی‌تر")

    # ─── لایه ۷: Volume Spread Analysis (10 امتیاز) ──────────
    last_3 = ltf_candles[-3:]
    avg_vol = sum(c["volume"] for c in ltf_candles[-20:]) / 20
    last_vol = last_3[-1]["volume"]
    last_body = abs(last_3[-1]["close"] - last_3[-1]["open"])
    last_range = last_3[-1]["high"] - last_3[-1]["low"]
    wick_ratio = (last_range - last_body) / last_range if last_range > 0 else 0

    if last_vol > avg_vol * 1.3 and wick_ratio < 0.4:
        score += 8
        reasons.append("✅ حجم بالا + بدنه بزرگ (مشارکت نهادی)")
    elif last_vol > avg_vol * 1.5 and wick_ratio > 0.6:
        warnings.append("⚠️ حجم بالا + ویک بلند (جذب یا رد سفارش)")

    # ─── لایه ۸: سشن (5 امتیاز) ────────────────────────────
    session, session_desc = detect_session()
    if session in ["LONDON", "NEWYORK"]:
        score += 5
        reasons.append(f"✅ {session_desc}")
    else:
        warnings.append(f"⚠️ {session_desc} - احتمال کم‌نوسانی")

    # محاسبه SL/TP
    extras = {
        "price": price,
        "atr": atr,
        "rsi": rsi_ltf,
        "session": session,
        "amd_phase": detect_amd_phase(ltf_candles),
        "htf_structure": htf_struct,
        "ltf_structure": ltf_struct,
        "active_ob": active_ob,
        "eqh": eqh,
        "eql": eql,
    }

    # محاسبه SL/TP بر اساس ATR
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


# ═══════════════════════════════════════════════════════════
#  📊  آنالیز اصلی هر سیمبول
# ═══════════════════════════════════════════════════════════

def analyze_symbol(symbol):
    """آنالیز کامل یک سیمبول و تولید سیگنال"""
    ltf_candles = get_klines(symbol, LTF, 50)
    itf_candles = get_klines(symbol, ITF, 100)

    if not ltf_candles or not itf_candles:
        return None

    price = ltf_candles[-1]["close"]
    _, _, ltf_choch = detect_market_structure(ltf_candles)
    _, _, itf_choch = detect_market_structure(itf_candles)

    amd = detect_amd_phase(ltf_candles)
    itf_obs = find_order_blocks(itf_candles)
    itf_fvgs = find_fvg(itf_candles)

    signals = []

    # تشخیص جهت بر اساس CHoCH و OB/FVG
    for direction in ["LONG", "SHORT"]:
        # شرط ورود: CHoCH یا BOS وجود داشته باشه
        choch_signal = (
            (direction == "LONG" and ltf_choch == "BULLISH_CHoCH") or
            (direction == "SHORT" and ltf_choch == "BEARISH_CHoCH") or
            (direction == "LONG" and itf_choch == "BULLISH_CHoCH") or
            (direction == "SHORT" and itf_choch == "BEARISH_CHoCH")
        )

        # وجود OB در جهت
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

        # حداقل یکی از شرایط باشه تا اسکور بگیریم
        if choch_signal or ob_exists or fvg_exists:
            score, reasons, warnings, extras = score_signal(symbol, direction)
            if score >= MIN_SCORE:
                signals.append({
                    "symbol": symbol,
                    "direction": direction,
                    "score": score,
                    "reasons": reasons,
                    "warnings": warnings,
                    "extras": extras
                })

    # فقط بهترین سیگنال رو برمیگردونیم
    if signals:
        return max(signals, key=lambda x: x["score"])
    return None


# ═══════════════════════════════════════════════════════════
#  📨  فرمت پیام تلگرام
# ═══════════════════════════════════════════════════════════

def format_signal_message(sig):
    """ساخت پیام زیبا برای تلگرام"""
    e = sig["extras"]
    d = sig["direction"]
    symbol = sig["symbol"]
    score = sig["score"]
    price = e["price"]

    emoji = "🟢" if d == "LONG" else "🔴"
    dir_fa = "خرید (LONG)" if d == "LONG" else "فروش (SHORT)"
    amd_emoji = {"ACCUMULATION": "🔵", "MANIPULATION_UP": "⬆️", "MANIPULATION_DOWN": "⬇️",
                 "DISTRIBUTION": "🟡", "TRANSITION": "⚪"}.get(e["amd_phase"], "⚪")
    struct_map = {"BULLISH": "📈 صعودی", "BEARISH": "📉 نزولی", "NEUTRAL": "↔️ خنثی"}

    quality = "💎 عالی" if score >= 85 else ("✨ خوب" if score >= 70 else "⚡ متوسط")
    session, _ = detect_session()

    msg = f"""
{emoji}{'─' * 30}
🎯 *سیگنال اسکلپ SMC*
{'─' * 30}
🪙 *{symbol}*  |  {dir_fa}
💰 قیمت فعلی: `{price:.6f}`
📊 کیفیت: {quality} ({score}/100)
⏰ سشن: {session}
{amd_emoji} فاز AMD: {e['amd_phase']}
{'─' * 30}
🏗️ *ساختار بازار*
  • HTF ({HTF}): {struct_map.get(e['htf_structure'], e['htf_structure'])}
  • LTF ({LTF}): {struct_map.get(e['ltf_structure'], e['ltf_structure'])}
  • RSI: {e['rsi']:.1f}
{'─' * 30}
🎰 *مدیریت معامله*
  🔴 استاپ لاس: `{e['sl']:.6f}`
  🎯 TP1 (1.5R): `{e['tp1']:.6f}`
  🎯 TP2 (2.5R): `{e['tp2']:.6f}`
  🎯 TP3 (4R):   `{e['tp3']:.6f}`"""

    if "tp_liquidity" in e:
        msg += f"\n  💧 هدف نقدینگی: `{e['tp_liquidity']:.6f}`"

    msg += f"\n  📐 R:R نسبت: 1:{e['rr']:.1f}"

    msg += f"\n{'─' * 30}\n✅ *تأییدیه‌ها*"
    for r in sig["reasons"][:6]:
        msg += f"\n  {r}"

    if sig["warnings"]:
        msg += f"\n{'─' * 30}\n⚠️ *هشدارها*"
        for w in sig["warnings"][:3]:
            msg += f"\n  {w}"

    msg += f"\n{'─' * 30}"
    msg += f"\n📌 *قانون SMC: فقط با جهت HTF معامله کن!*"
    msg += f"\n⚠️ _این سیگنال صرفاً آموزشی است_"
    msg += f"\n🕐 {datetime.now().strftime('%H:%M:%S')} | `@SMC_ScalpBot`"

    return msg


def send_telegram(message):
    """ارسال پیام به تلگرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        return False


def send_market_summary():
    """ارسال خلاصه وضعیت بازار"""
    session, session_desc = detect_session()
    btc = get_klines("BTCUSDT", "1h", 50)
    if not btc:
        return

    btc_struct, _, _ = detect_market_structure(btc)
    btc_rsi = calculate_rsi(btc)
    btc_price = btc[-1]["close"]
    ticker = get_ticker("BTCUSDT")
    change_24h = float(ticker.get("priceChangePercent", 0))
    change_emoji = "📈" if change_24h > 0 else "📉"

    msg = f"""
🌐{'─' * 28}
📊 *خلاصه بازار - SMC Bot*
{'─' * 30}
⏰ سشن فعال: {session_desc}
🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC
{'─' * 30}
₿ BTC/USDT: `${btc_price:,.2f}`
  {change_emoji} تغییر ۲۴ ساعته: {change_24h:+.2f}%
  📐 ساختار H1: {'📈 صعودی' if btc_struct=='BULLISH' else ('📉 نزولی' if btc_struct=='BEARISH' else '↔️ خنثی')}
  📊 RSI: {btc_rsi:.1f}
{'─' * 30}
🔎 در حال اسکن {len(SYMBOLS)} ارز...
🎯 حداقل امتیاز سیگنال: {MIN_SCORE}/100
{'─' * 30}
📚 *اصول SMC فعال:*
  • ساختار HTF/ITF/LTF
  • Order Block + FVG
  • CHoCH + BOS
  • نقدینگی EQH/EQL
  • فاز AMD (Wyckoff)
"""
    send_telegram(msg)


# ═══════════════════════════════════════════════════════════
#  🚀  اجرای اصلی
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 50)
    print("  SMC Scalp Signal Bot - Starting...")
    print("=" * 50)
    print(f"  Symbols : {', '.join(SYMBOLS)}")
    print(f"  HTF={HTF} | ITF={ITF} | LTF={LTF}")
    print(f"  Min Score: {MIN_SCORE}/100")
    print(f"  Interval: {CHECK_INTERVAL_MINUTES} min")
    print("=" * 50)

    # چک کردن اتصال تلگرام
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("[!] لطفاً TELEGRAM_TOKEN و TELEGRAM_CHAT_ID رو تنظیم کن!")
        return

    startup_msg = f"🤖 *SMC Scalp Bot راه‌اندازی شد!*\n\n✅ اتصال برقرار\n📊 سیمبول‌ها: {', '.join(SYMBOLS)}\n⏱ هر {CHECK_INTERVAL_MINUTES} دقیقه اسکن"
    send_telegram(startup_msg)
    print("[OK] ربات شروع به کار کرد")

    cycle = 0
    while True:
        cycle += 1
        print(f"\n[Cycle {cycle}] {datetime.now().strftime('%H:%M:%S')} - Scanning...")

        # هر ۴ سیکل خلاصه بازار بفرست
        if cycle % 4 == 1:
            send_market_summary()
            print("[INFO] Market summary sent")

        signals_found = 0
        for symbol in SYMBOLS:
            print(f"  → Analyzing {symbol}...", end=" ")
            try:
                sig = analyze_symbol(symbol)
                if sig:
                    msg = format_signal_message(sig)
                    if send_telegram(msg):
                        signals_found += 1
                        print(f"✅ Signal! ({sig['direction']} | Score:{sig['score']})")
                    else:
                        print("❌ Telegram error")
                else:
                    print("No signal")
                time.sleep(1.5)  # برای جلوگیری از rate limit
            except Exception as ex:
                print(f"ERROR: {ex}")
                time.sleep(2)

        print(f"[Done] {signals_found} signal(s) sent. Next scan in {CHECK_INTERVAL_MINUTES} min")
        time.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
