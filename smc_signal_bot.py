#!/usr/bin/env python3
"""
╔══════════════════════════════════════╗
║   INSTITUTIONAL SMC SIGNAL ENGINE   ║
║   Pure Price Action | No Indicators ║
║   Anti-Duplicate | Best 2 Signals   ║
╚══════════════════════════════════════╝
"""

import os, requests, time, json
from datetime import datetime, timezone

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ── ۳۰ ارز برتر برای مقایسه ──
SYMBOLS = [
    "BTC-USDT","ETH-USDT","BNB-USDT","XRP-USDT","SOL-USDT",
    "ADA-USDT","DOGE-USDT","AVAX-USDT","DOT-USDT","LINK-USDT",
    "MATIC-USDT","LTC-USDT","UNI-USDT","ATOM-USDT","APT-USDT",
    "NEAR-USDT","OP-USDT","ARB-USDT","INJ-USDT","SUI-USDT",
    "FIL-USDT","AAVE-USDT","MKR-USDT","GMX-USDT","DYDX-USDT",
    "STX-USDT","RUNE-USDT","FET-USDT","WLD-USDT","TIA-USDT"
]

# فایل ذخیره پوزیشن‌های باز
STATE_FILE = "/tmp/smc_state.json"

BASE_URL = "https://api.kucoin.com"
HTF, ITF, LTF = "1hour", "15min", "5min"

# ══════════════════════════════════
#  STATE MANAGER - ضد تکرار
# ══════════════════════════════════

STATE_FILE = "/tmp/smc_state.json"

def load_state():
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"limit": 1, "offset": -1}, timeout=10)
        msgs = r.json().get("result", [])
        for m in reversed(msgs):
            text = m.get("message", {}).get("text", "")
            if text.startswith("STATE:"):
                return json.loads(text[6:])
    except:
        pass
    return {"open": {}}

def save_state(state):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"STATE:{json.dumps(state)}",
                "disable_notification": True
            }, timeout=10)
    except:
        pass

def is_position_open(state, symbol, direction):
    key = f"{symbol}_{direction}"
    return key in state["open_positions"]

def open_position(state, symbol, direction, sl, tp1, tp2, price):
    key = f"{symbol}_{direction}"
    state["open_positions"][key] = {
        "symbol": symbol,
        "direction": direction,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "time": datetime.now().strftime("%H:%M")
    }
    save_state(state)

def check_and_close_positions(state, symbol, current_price):
    """چک کن آیا SL یا TP خورده"""
    closed = []
    keys_to_remove = []
    for key, pos in state["open_positions"].items():
        if pos["symbol"] != symbol:
            continue
        d = pos["direction"]
        sl, tp1, tp2 = pos["sl"], pos["tp1"], pos["tp2"]
        entry = pos["entry"]

        if d == "LONG":
            if current_price <= sl:
                closed.append({"pos": pos, "result": "SL_HIT", "pnl": round((sl/entry-1)*100, 2)})
                keys_to_remove.append(key)
            elif current_price >= tp2:
                closed.append({"pos": pos, "result": "TP2_HIT", "pnl": round((tp2/entry-1)*100, 2)})
                keys_to_remove.append(key)
            elif current_price >= tp1:
                # TP1 خورده - SL رو به ورود بکش
                state["open_positions"][key]["sl"] = entry
        else:  # SHORT
            if current_price >= sl:
                closed.append({"pos": pos, "result": "SL_HIT", "pnl": round((1-sl/entry)*100, 2)})
                keys_to_remove.append(key)
            elif current_price <= tp2:
                closed.append({"pos": pos, "result": "TP2_HIT", "pnl": round((1-tp2/entry)*100, 2)})
                keys_to_remove.append(key)
            elif current_price <= tp1:
                state["open_positions"][key]["sl"] = entry

    for key in keys_to_remove:
        del state["open_positions"][key]

    if keys_to_remove:
        save_state(state)

    return closed

# ══════════════════════════════════
#  DATA ENGINE
# ══════════════════════════════════

def get_klines(symbol, interval, limit=200):
    try:
        r = requests.get(f"{BASE_URL}/api/v1/market/candles",
                         params={"symbol": symbol, "type": interval},
                         timeout=10)
        raw = r.json().get("data", [])[:limit]
        return [{"o": float(d[1]), "c": float(d[2]),
                 "h": float(d[3]), "l": float(d[4]),
                 "v": float(d[5])} for d in reversed(raw)]
    except:
        return []

# ══════════════════════════════════
#  PURE PRICE ACTION ENGINE
#  (بدون اندیکاتور - فقط پرایس اکشن)
# ══════════════════════════════════

def find_swing_highs(candles, lb=5):
    """Swing High واقعی با lookback دقیق"""
    result = []
    for i in range(lb, len(candles)-lb):
        if all(candles[i]["h"] > candles[j]["h"]
               for j in range(i-lb, i+lb+1) if j != i):
            result.append({"price": candles[i]["h"], "idx": i})
    return result

def find_swing_lows(candles, lb=5):
    """Swing Low واقعی"""
    result = []
    for i in range(lb, len(candles)-lb):
        if all(candles[i]["l"] < candles[j]["l"]
               for j in range(i-lb, i+lb+1) if j != i):
            result.append({"price": candles[i]["l"], "idx": i})
    return result

def get_market_structure(candles):
    """
    ساختار بازار کامل:
    - HH/HL = Bullish
    - LH/LL = Bearish
    - CHoCH = تغییر کاراکتر (ورود ایده‌آل)
    - BOS = شکست ساختار (تأیید)
    """
    sh = find_swing_highs(candles)
    sl = find_swing_lows(candles)
    if len(sh) < 3 or len(sl) < 3:
        return {"trend": "NEUTRAL", "choch": None, "bos": None,
                "last_high": 0, "last_low": 0}

    last_high = sh[-1]["price"]
    prev_high = sh[-2]["price"]
    last_low  = sl[-1]["price"]
    prev_low  = sl[-2]["price"]
    price     = candles[-1]["c"]

    # تعیین روند
    if last_high > prev_high and last_low > prev_low:
        trend = "BULLISH"
    elif last_high < prev_high and last_low < prev_low:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    # BOS - شکست ساختار در جهت روند
    bos = None
    if trend == "BULLISH" and price > last_high:
        bos = "BULLISH"
    elif trend == "BEARISH" and price < last_low:
        bos = "BEARISH"

    # CHoCH - مهمترین سیگنال (شکست خلاف روند)
    choch = None
    if trend == "BULLISH" and price < prev_low:
        choch = "BEARISH_CHOCH"
    elif trend == "BEARISH" and price > prev_high:
        choch = "BULLISH_CHOCH"

    return {"trend": trend, "choch": choch, "bos": bos,
            "last_high": last_high, "last_low": last_low,
            "prev_high": prev_high, "prev_low": prev_low}

def find_premium_order_blocks(candles):
    """
    Order Block کلاسیک ICT:
    - آخرین کندل مخالف قبل از ایمپالس که BOS ایجاد کرد
    - قوی‌ترین نوع OB
    """
    bull_obs = []
    bear_obs = []
    sh = find_swing_highs(candles, lb=3)
    sl = find_swing_lows(candles, lb=3)

    for i in range(5, len(candles)-5):
        c = candles[i]
        body = abs(c["c"] - c["o"])
        if body == 0:
            continue

        # بررسی ایمپالس بعدی
        future_high = max(candles[j]["h"] for j in range(i+1, min(i+8, len(candles))))
        future_low  = min(candles[j]["l"] for j in range(i+1, min(i+8, len(candles))))

        # Bullish OB: کندل نزولی + ایمپالس صعودی قوی
        if (c["c"] < c["o"] and
                future_high > c["h"] * 1.003):
            impulse_size = future_high - c["h"]
            if impulse_size > body * 0.8:
                bull_obs.append({
                    "top": c["o"],
                    "bottom": c["l"],
                    "mid": (c["o"] + c["l"]) / 2,
                    "idx": i,
                    "impulse": impulse_size / body
                })

        # Bearish OB: کندل صعودی + ایمپالس نزولی قوی
        if (c["c"] > c["o"] and
                future_low < c["l"] * 0.997):
            impulse_size = c["l"] - future_low
            if impulse_size > body * 0.8:
                bear_obs.append({
                    "top": c["h"],
                    "bottom": c["o"],
                    "mid": (c["h"] + c["o"]) / 2,
                    "idx": i,
                    "impulse": impulse_size / body
                })

    return bull_obs[-4:], bear_obs[-4:]

def find_fvg(candles):
    """
    Fair Value Gap (Imbalance):
    فضایی که قیمت بدون معامله رد شده و باید برگرده پرش کنه
    """
    bull_fvg, bear_fvg = [], []
    for i in range(len(candles)-2):
        c1, c2, c3 = candles[i], candles[i+1], candles[i+2]
        # Bullish FVG: Low کندل ۳ > High کندل ۱
        if c3["l"] > c1["h"]:
            size = c3["l"] - c1["h"]
            bull_fvg.append({
                "top": c3["l"], "bottom": c1["h"],
                "mid": (c3["l"] + c1["h"]) / 2,
                "size": size, "idx": i+1
            })
        # Bearish FVG
        if c3["h"] < c1["l"]:
            size = c1["l"] - c3["h"]
            bear_fvg.append({
                "top": c1["l"], "bottom": c3["h"],
                "mid": (c1["l"] + c3["h"]) / 2,
                "size": size, "idx": i+1
            })
    return bull_fvg[-5:], bear_fvg[-5:]

def find_liquidity_pools(candles):
    """
    Equal Highs/Lows = استخرهای نقدینگی
    جایی که استاپ‌های رتیل جمع شده
    """
    highs = [c["h"] for c in candles[-50:]]
    lows  = [c["l"] for c in candles[-50:]]
    tol = 0.001
    bsl, ssl = [], []

    for i in range(len(highs)):
        for j in range(i+4, len(highs)):
            if highs[i] == 0: continue
            if abs(highs[i]-highs[j])/highs[i] < tol:
                lvl = (highs[i]+highs[j])/2
                if not any(abs(z-lvl)/lvl < tol for z in bsl):
                    bsl.append(lvl)

    for i in range(len(lows)):
        for j in range(i+4, len(lows)):
            if lows[i] == 0: continue
            if abs(lows[i]-lows[j])/lows[i] < tol:
                lvl = (lows[i]+lows[j])/2
                if not any(abs(z-lvl)/lvl < tol for z in ssl):
                    ssl.append(lvl)

    return sorted(bsl)[-3:], sorted(ssl)[:3]

def detect_imbalance_zone(candles):
    """
    تشخیص زون عدم تعادل:
    کندل‌هایی که body بزرگ و wick کوچک دارن = ایمپالس واقعی
    """
    imbalances = []
    for i in range(len(candles)-1):
        c = candles[i]
        body  = abs(c["c"] - c["o"])
        range_ = c["h"] - c["l"]
        if range_ == 0: continue
        body_ratio = body / range_
        # کندل با body بیش از ۷۰٪ range = ایمپالس قوی
        if body_ratio > 0.7 and body > 0:
            imbalances.append({
                "bullish": c["c"] > c["o"],
                "top": c["h"],
                "bottom": c["l"],
                "body_ratio": body_ratio,
                "idx": i
            })
    return imbalances[-5:]

def get_session():
    h = datetime.now(timezone.utc).hour
    if 7 <= h < 10:   return "LONDON OPEN 🇬🇧", 15
    elif 10 <= h < 12: return "LONDON 🇬🇧", 10
    elif 12 <= h < 16: return "NEW YORK OPEN 🗽", 15
    elif 16 <= h < 20: return "NEW YORK 🗽", 10
    elif 0 <= h < 7:   return "ASIAN 🌏", 3
    return "OVERLAP", 5

def calc_atr(candles, p=14):
    trs = []
    for i in range(1, len(candles)):
        h,l,pc = candles[i]["h"],candles[i]["l"],candles[i-1]["c"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-p:]) / min(p, len(trs)) if trs else 0

def volume_analysis(candles):
    """تحلیل حجم برای تأیید حرکت"""
    if len(candles) < 21:
        return 1, False
    avg = sum(c["v"] for c in candles[-21:-1]) / 20
    last = candles[-1]["v"]
    last3 = sum(c["v"] for c in candles[-4:-1]) / 3
    ratio = last / avg if avg > 0 else 1
    increasing = last3 > avg * 1.1
    return round(ratio, 2), increasing

# ══════════════════════════════════
#  MAIN ANALYSIS ENGINE
# ══════════════════════════════════

def analyze_symbol(symbol):
    """
    تحلیل کامل یک ارز با pure price action
    خروجی: بهترین سیگنال یا None
    """
    htf = get_klines(symbol, HTF, 200)
    itf = get_klines(symbol, ITF, 200)
    ltf = get_klines(symbol, LTF, 100)

    if len(htf) < 50 or len(itf) < 50 or len(ltf) < 20:
        return None

    price = ltf[-1]["c"]
    atr   = calc_atr(ltf)
    if price == 0 or atr == 0:
        return None

    # ساختار ۳ تایم‌فریم
    htf_ms = get_market_structure(htf)
    itf_ms = get_market_structure(itf)
    ltf_ms = get_market_structure(ltf)

    # OB, FVG, Liquidity از ITF
    bull_ob, bear_ob = find_premium_order_blocks(itf)
    bull_fvg, bear_fvg = find_fvg(itf)
    bsl, ssl = find_liquidity_pools(itf)

    # Imbalance از LTF
    imbalances = detect_imbalance_zone(ltf)

    session, session_pts = get_session()
    vol_ratio, vol_inc = volume_analysis(ltf)

    best = None

    for direction in ["LONG", "SHORT"]:
        score = 0
        confluence = []  # عوامل همگرایی
        invalidations = []  # عوامل رد سیگنال

        # ══ RULE 1: HTF Bias (اجباری) ══
        htf_aligned = (direction == "LONG" and htf_ms["trend"] == "BULLISH") or \
                      (direction == "SHORT" and htf_ms["trend"] == "BEARISH")
        if htf_aligned:
            score += 25
            confluence.append(f"HTF {htf_ms['trend']}")
        elif htf_ms["trend"] == "NEUTRAL":
            score += 5
        else:
            invalidations.append("COUNTER HTF TREND")
            score -= 20

        # ══ RULE 2: ITF Confirmation ══
        itf_aligned = (direction == "LONG" and itf_ms["trend"] in ["BULLISH","NEUTRAL"]) or \
                      (direction == "SHORT" and itf_ms["trend"] in ["BEARISH","NEUTRAL"])
        if itf_aligned:
            score += 15
            confluence.append(f"ITF {itf_ms['trend']}")

        # ══ RULE 3: CHoCH / BOS (ورود ایده‌آل) ══
        if direction == "LONG":
            if ltf_ms["choch"] == "BULLISH_CHOCH":
                score += 25
                confluence.append("LTF BULLISH CHoCH ⚡")
            elif itf_ms["choch"] == "BULLISH_CHOCH":
                score += 20
                confluence.append("ITF BULLISH CHoCH")
            elif ltf_ms["bos"] == "BULLISH":
                score += 12
                confluence.append("LTF BULLISH BOS")
            elif itf_ms["bos"] == "BULLISH":
                score += 8
                confluence.append("ITF BULLISH BOS")
        else:
            if ltf_ms["choch"] == "BEARISH_CHOCH":
                score += 25
                confluence.append("LTF BEARISH CHoCH ⚡")
            elif itf_ms["choch"] == "BEARISH_CHOCH":
                score += 20
                confluence.append("ITF BEARISH CHoCH")
            elif ltf_ms["bos"] == "BEARISH":
                score += 12
                confluence.append("LTF BEARISH BOS")
            elif itf_ms["bos"] == "BEARISH":
                score += 8
                confluence.append("ITF BEARISH BOS")

        # ══ RULE 4: Order Block ══
        ob_active = None
        if direction == "LONG":
            for ob in reversed(bull_ob):
                if ob["bottom"] * 0.998 <= price <= ob["top"] * 1.003:
                    score += 20
                    confluence.append(f"BULLISH OB ({ob['impulse']:.1f}x impulse)")
                    ob_active = ob
                    break
        else:
            for ob in reversed(bear_ob):
                if ob["bottom"] * 0.997 <= price <= ob["top"] * 1.002:
                    score += 20
                    confluence.append(f"BEARISH OB ({ob['impulse']:.1f}x impulse)")
                    ob_active = ob
                    break

        # ══ RULE 5: FVG (Fair Value Gap) ══
        fvg_active = None
        if direction == "LONG":
            for fvg in reversed(bull_fvg):
                if fvg["bottom"] <= price <= fvg["top"]:
                    score += 15
                    confluence.append("BULLISH FVG (Imbalance)")
                    fvg_active = fvg
                    break
        else:
            for fvg in reversed(bear_fvg):
                if fvg["bottom"] <= price <= fvg["top"]:
                    score += 15
                    confluence.append("BEARISH FVG (Imbalance)")
                    fvg_active = fvg
                    break

        # ══ RULE 6: Liquidity Sweep ══
        if direction == "LONG":
            # قیمت SSL رو زد و برگشت (Stop Hunt)
            for lvl in ssl:
                if ltf_ms["last_low"] < lvl * 1.002 and price > lvl:
                    score += 15
                    confluence.append(f"SSL SWEPT @ {lvl:.4f}")
                    break
        else:
            for lvl in bsl:
                if ltf_ms["last_high"] > lvl * 0.998 and price < lvl:
                    score += 15
                    confluence.append(f"BSL SWEPT @ {lvl:.4f}")
                    break

        # ══ RULE 7: Target Liquidity ══
        tp_target = None
        if direction == "LONG" and bsl:
            nearest_bsl = min((l for l in bsl if l > price), default=None)
            if nearest_bsl:
                tp_target = nearest_bsl
                confluence.append(f"TARGET: BSL @ {nearest_bsl:.4f}")
        elif direction == "SHORT" and ssl:
            nearest_ssl = max((l for l in ssl if l < price), default=None)
            if nearest_ssl:
                tp_target = nearest_ssl
                confluence.append(f"TARGET: SSL @ {nearest_ssl:.4f}")

        # ══ RULE 8: Volume Confirmation ══
        if vol_ratio > 1.3 and vol_inc:
            score += 10
            confluence.append(f"VOLUME SURGE ({vol_ratio}x)")
        elif vol_ratio < 0.5:
            invalidations.append("LOW VOLUME")
            score -= 8

        # ══ RULE 9: Session ══
        score += session_pts
        if session_pts >= 10:
            confluence.append(f"PRIME SESSION: {session}")

        # ══ RULE 10: Imbalance Candle ══
        recent_imb = [i for i in imbalances if i["idx"] >= len(ltf)-6]
        for imb in recent_imb:
            if direction == "LONG" and imb["bullish"]:
                score += 8
                confluence.append("BULLISH IMPULSE CANDLE")
            elif direction == "SHORT" and not imb["bullish"]:
                score += 8
                confluence.append("BEARISH IMPULSE CANDLE")

        # فیلتر: حداقل ۳ تأییدیه اصلی
        main_confirmations = sum([
            1 for c in confluence
            if any(k in c for k in ["CHoCH","BOS","OB","FVG","SWEPT"])
        ])
        if main_confirmations < 2:
            continue

        # فیلتر: امتیاز کافی
        if score < 65:
            continue

        # محاسبه SL/TP هوشمند
        sh_list = find_swing_highs(ltf, lb=3)
        sl_list = find_swing_lows(ltf, lb=3)

        if direction == "LONG":
            # SL: زیر آخرین Swing Low
            sl_price = sl_list[-1]["price"] * 0.9985 if sl_list else price - atr * 1.5
            sl_price = min(sl_price, price - atr * 1.0)  # حداقل ۱ ATR
            tp1_price = price + (price - sl_price) * 1.5
            tp2_price = tp_target if tp_target and tp_target > price else \
                        price + (price - sl_price) * 3.0
        else:
            # SL: بالای آخرین Swing High
            sl_price = sh_list[-1]["price"] * 1.0015 if sh_list else price + atr * 1.5
            sl_price = max(sl_price, price + atr * 1.0)
            tp1_price = price - (sl_price - price) * 1.5
            tp2_price = tp_target if tp_target and tp_target < price else \
                        price - (sl_price - price) * 3.0

        sl_dist = abs(price - sl_price)
        rr = abs(tp2_price - price) / sl_dist if sl_dist > 0 else 0

        # فیلتر: R:R حداقل ۲
        if rr < 2.0:
            continue

        # درصد SL
        sl_pct = round(abs(price - sl_price) / price * 100, 2)
        tp1_pct = round(abs(tp1_price - price) / price * 100, 2)
        tp2_pct = round(abs(tp2_price - price) / price * 100, 2)

        result = {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "price": round(price, 8),
            "sl": round(sl_price, 8),
            "tp1": round(tp1_price, 8),
            "tp2": round(tp2_price, 8),
            "rr": round(rr, 1),
            "sl_pct": sl_pct,
            "tp1_pct": tp1_pct,
            "tp2_pct": tp2_pct,
            "session": session,
            "confluence": confluence,
            "invalidations": invalidations,
            "vol_ratio": vol_ratio,
            "htf_trend": htf_ms["trend"],
            "main_conf": main_confirmations,
        }

        if best is None or score > best["score"]:
            best = result

    return best

# ══════════════════════════════════
#  MESSAGE FORMATTER
# ══════════════════════════════════

def format_signal(s, rank=1):
    sym = s["symbol"].replace("-", "/")
    is_long = s["direction"] == "LONG"

    # استیکرها
    dir_sticker = "📈" if is_long else "📉"
    rank_icon = "🥇" if rank == 1 else "🥈"
    quality_icon = "💎" if s["score"] >= 85 else ("🔥" if s["score"] >= 75 else "⚡")

    # درجه اطمینان
    confidence = min(99, int(s["score"] * 0.98))

    side = "LONG  🟢" if is_long else "SHORT 🔴"

    msg = f"""{rank_icon} {dir_sticker} #{rank} SIGNAL  |  {quality_icon} {confidence}% Confidence

🪙 {sym}
📊 {side}
⏰ {s['session']}
{'━'*26}
💰 ENTRY:   {s['price']}
🛑 SL:      {s['sl']}  (-{s['sl_pct']}%)
🎯 TP1:     {s['tp1']}  (+{s['tp1_pct']}%)
🎯 TP2:     {s['tp2']}  (+{s['tp2_pct']}%)
📐 R:R      1:{s['rr']}
{'━'*26}
📋 CONFLUENCE ({s['main_conf']} key factors):"""

    for c in s["confluence"][:5]:
        msg += f"\n  ✅ {c}"

    if s["invalidations"]:
        msg += f"\n  ⚠️ {s['invalidations'][0]}"

    msg += f"\n{'━'*26}"
    msg += f"\n📊 Vol: {s['vol_ratio']}x avg"
    msg += f"\n🏗 HTF Bias: {s['htf_trend']}"
    msg += f"\n🕐 {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
    msg += f"\n{'━'*26}"
    msg += f"\n⚠️ Risk max 1-2% per trade"
    msg += f"\n📌 Move SL to entry after TP1"

    return msg

def format_result(pos, result, current_price):
    sym = pos["symbol"].replace("-","")
    if result == "TP2_HIT":
        pnl = round(abs(pos["tp2"]/pos["entry"]-1)*100, 2)
        return f"""🏆 TRADE CLOSED - FULL WIN!
{'━'*24}
🪙 {sym} {pos['direction']}
✅ TP2 HIT +{pnl}%
Entry: {pos['entry']}
Exit:  {current_price}
{'━'*24}
💰 Excellent execution!"""
    else:
        pnl = round(abs(pos["sl"]/pos["entry"]-1)*100, 2)
        return f"""❌ TRADE CLOSED - SL HIT
{'━'*24}
🪙 {sym} {pos['direction']}
🛑 Stop Loss -{pnl}%
Entry: {pos['entry']}
Exit:  {current_price}
{'━'*24}
📌 Risk was managed. Next!"""

# ══════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════

def send_tg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True
        }, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"[TG ERR] {e}")
        return False

def send_sticker(sticker_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendSticker"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "sticker": sticker_id
        }, timeout=10)
    except:
        pass

# استیکرهای تلگرام
STICKER_SIGNAL = "CAACAgIAAxkBAAIBsWWfAAGKJwABhBKNpMoHZV2lE6UZAAJ4AQACB8xhS5mHETfIBCFhHgQ"
STICKER_WIN    = "CAACAgIAAxkBAAIBs2WfAAGMJwABhBKNpMoHZV2lE6UZAAJ5AQACB8xhS5mHETfIBCFhHgQ"
STICKER_LOSS   = "CAACAgIAAxkBAAIBtWWfAAGOJwABhBKNpMoHZV2lE6UZAAJ6AQACB8xhS5mHETfIBCFhHgQ"

# ══════════════════════════════════
#  MAIN
# ══════════════════════════════════

def main():
    print("=" * 40)
    print("  INSTITUTIONAL SMC BOT STARTING")
    print("=" * 40)

    if not TELEGRAM_TOKEN:
        print("ERROR: No Telegram token!")
        return

    state = load_state()

    # ── چک پوزیشن‌های باز ──
    for symbol in list(state["open_positions"].keys()):
        sym = symbol.rsplit("_", 1)[0]
        ltf = get_klines(sym, LTF, 10)
        if ltf:
            current = ltf[-1]["c"]
            closed = check_and_close_positions(state, sym, current)
            for c in closed:
                msg = format_result(c["pos"], c["result"], current)
                if c["result"] == "TP2_HIT":
                    send_sticker(STICKER_WIN)
                else:
                    send_sticker(STICKER_LOSS)
                send_tg(msg)
                time.sleep(0.5)

    # ── اسکن همه ارزها ──
    print(f"\nScanning {len(SYMBOLS)} symbols...")
    candidates = []

    for symbol in SYMBOLS:
        print(f"  {symbol}...", end=" ", flush=True)
        try:
            # اگه پوزیشن باز داریم، رد کن
            pos_long  = is_position_open(state, symbol, "LONG")
            pos_short = is_position_open(state, symbol, "SHORT")
            if pos_long and pos_short:
                print("has positions - skip")
                time.sleep(0.5)
                continue

            sig = analyze_symbol(symbol)
            if sig:
                # چک کن همین جهت باز نباشه
                if is_position_open(state, symbol, sig["direction"]):
                    print(f"already open {sig['direction']} - skip")
                    time.sleep(0.5)
                    continue
                candidates.append(sig)
                print(f"✓ {sig['direction']} score:{sig['score']}")
            else:
                print("no signal")
            time.sleep(1.0)
        except Exception as e:
            print(f"ERR: {e}")
            time.sleep(1)

    # ── انتخاب ۲ بهترین ──
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top2 = candidates[:2]

    if top2:
        print(f"\nSending {len(top2)} top signals...")
        send_sticker(STICKER_SIGNAL)
        time.sleep(0.3)

        for i, sig in enumerate(top2, 1):
            msg = format_signal(sig, rank=i)
            if send_tg(msg):
                open_position(state, sig["symbol"], sig["direction"],
                              sig["sl"], sig["tp1"], sig["tp2"], sig["price"])
                print(f"  Sent #{i}: {sig['symbol']} {sig['direction']} {sig['score']}")
            time.sleep(1)
    else:
        now = datetime.now(timezone.utc).strftime("%H:%M")
        send_tg(f"🔍 Scan Complete — {len(SYMBOLS)} pairs analyzed\n"
                f"❌ No high-quality signals found\n"
                f"🕐 {now} UTC\n"
                f"⏳ Next scan in 30 min")
        print("No signals found")

    print("\nDone!")

if __name__ == "__main__":
    main()

