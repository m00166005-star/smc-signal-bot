#!/usr/bin/env python3

import os, requests, time, json
from datetime import datetime, timezone

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOLS = [
    "BTC-USDT","ETH-USDT","BNB-USDT","XRP-USDT","SOL-USDT",
    "ADA-USDT","DOGE-USDT","AVAX-USDT","DOT-USDT","LINK-USDT",
    "MATIC-USDT","LTC-USDT","UNI-USDT","ATOM-USDT","APT-USDT",
    "NEAR-USDT","OP-USDT","ARB-USDT","INJ-USDT","SUI-USDT",
    "FIL-USDT","AAVE-USDT","MKR-USDT","GMX-USDT","DYDX-USDT",
    "STX-USDT","RUNE-USDT","FET-USDT","WLD-USDT","TIA-USDT"
]

BASE_URL = "https://api.kucoin.com"
HTF, ITF, LTF = "1hour", "15min", "5min"

# ══════════════════════════════════
#  STATE - ذخیره در تلگرام
# ══════════════════════════════════

def load_state():
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"limit": 100, "offset": -100}, timeout=10)
        results = r.json().get("result", [])
        for m in reversed(results):
            text = m.get("message", {}).get("text", "")
            if text.startswith("__STATE__:"):
                return json.loads(text[10:])
    except Exception as e:
        print(f"[STATE LOAD ERR] {e}")
    return {"open": {}}

def save_state(state):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"__STATE__:{json.dumps(state)}",
                "disable_notification": True
            }, timeout=10)
    except Exception as e:
        print(f"[STATE SAVE ERR] {e}")

def is_open(state, symbol, direction):
    return f"{symbol}_{direction}" in state["open"]

def add_position(state, sig):
    key = f"{sig['symbol']}_{sig['direction']}"
    state["open"][key] = {
        "symbol":    sig["symbol"],
        "direction": sig["direction"],
        "entry":     sig["price"],
        "sl":        sig["sl"],
        "tp1":       sig["tp1"],
        "tp2":       sig["tp2"],
        "msg":       sig.get("msg","")
    }
    save_state(state)

def check_closed(state, symbol, price):
    closed = []
    to_del = []
    for key, p in list(state["open"].items()):
        if p["symbol"] != symbol:
            continue
        if p["direction"] == "LONG":
            if price <= p["sl"]:
                closed.append((p, "SL")); to_del.append(key)
            elif price >= p["tp2"]:
                closed.append((p, "TP2")); to_del.append(key)
            elif price >= p["tp1"]:
                state["open"][key]["sl"] = p["entry"]
        else:
            if price >= p["sl"]:
                closed.append((p, "SL")); to_del.append(key)
            elif price <= p["tp2"]:
                closed.append((p, "TP2")); to_del.append(key)
            elif price <= p["tp1"]:
                state["open"][key]["sl"] = p["entry"]
    for k in to_del:
        del state["open"][k]
    if to_del:
        save_state(state)
    return closed

# ══════════════════════════════════
#  DATA
# ══════════════════════════════════

def get_klines(symbol, interval, limit=300):
    try:
        r = requests.get(f"{BASE_URL}/api/v1/market/candles",
                         params={"symbol": symbol, "type": interval},
                         timeout=10)
        raw = r.json().get("data", [])[:limit]
        return [{"o":float(d[1]),"c":float(d[2]),
                 "h":float(d[3]),"l":float(d[4]),"v":float(d[5])}
                for d in reversed(raw)]
    except:
        return []

# ══════════════════════════════════
#  INDICATORS
# ══════════════════════════════════

def calc_atr(candles, p=14):
    trs = [max(candles[i]["h"]-candles[i]["l"],
               abs(candles[i]["h"]-candles[i-1]["c"]),
               abs(candles[i]["l"]-candles[i-1]["c"]))
           for i in range(1, len(candles))]
    return sum(trs[-p:]) / min(p, len(trs)) if trs else 0

def calc_rsi(candles, p=14):
    closes = [c["c"] for c in candles]
    if len(closes) < p+1: return 50
    gains  = [max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses = [max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag = sum(gains[-p:])/p
    al = sum(losses[-p:])/p
    return round(100-(100/(1+ag/al)),1) if al else 100

def calc_ema(candles, p):
    closes = [c["c"] for c in candles]
    if len(closes) < p: return closes[-1]
    k = 2/(p+1)
    ema = sum(closes[:p])/p
    for c in closes[p:]: ema = c*k + ema*(1-k)
    return ema

def calc_volume_delta(candles, lookback=20):
    """
    تحلیل دلتای حجم:
    کندل‌های صعودی با حجم بالا = فشار خرید
    کندل‌های نزولی با حجم بالا = فشار فروش
    """
    recent = candles[-lookback:]
    buy_vol  = sum(c["v"] for c in recent if c["c"] >= c["o"])
    sell_vol = sum(c["v"] for c in recent if c["c"] < c["o"])
    total = buy_vol + sell_vol
    if total == 0: return 0.5
    return round(buy_vol / total, 3)  # > 0.55 = فشار خرید | < 0.45 = فشار فروش

def calc_avg_vol(candles, p=20):
    avg = sum(c["v"] for c in candles[-p-1:-1]) / p
    last = candles[-1]["v"]
    return round(last/avg, 2) if avg else 1

def detect_divergence(candles, rsi_vals, lookback=10):
    """
    واگرایی قیمت و RSI:
    Regular Bullish: قیمت LL میزنه ولی RSI LH
    Regular Bearish: قیمت HH میزنه ولی RSI LH میزنه
    """
    if len(candles) < lookback or len(rsi_vals) < lookback:
        return None
    prices = [c["c"] for c in candles[-lookback:]]
    rsis   = rsi_vals[-lookback:]
    # Bullish divergence
    if prices[-1] < prices[0] and rsis[-1] > rsis[0]:
        return "BULLISH_DIV"
    # Bearish divergence
    if prices[-1] > prices[0] and rsis[-1] < rsis[0]:
        return "BEARISH_DIV"
    return None

def calc_rsi_series(candles, p=14):
    """سری RSI برای تشخیص واگرایی"""
    closes = [c["c"] for c in candles]
    if len(closes) < p+2: return []
    series = []
    for i in range(p+1, len(closes)):
        sub = closes[:i+1]
        gains  = [max(sub[j]-sub[j-1],0) for j in range(1,len(sub))]
        losses = [max(sub[j-1]-sub[j],0) for j in range(1,len(sub))]
        ag = sum(gains[-p:])/p
        al = sum(losses[-p:])/p
        series.append(round(100-(100/(1+ag/al)),1) if al else 100)
    return series

# ══════════════════════════════════
#  PURE PRICE ACTION
# ══════════════════════════════════

def find_swings(candles, lb=5):
    highs, lows = [], []
    for i in range(lb, len(candles)-lb):
        if all(candles[i]["h"] >= candles[j]["h"]
               for j in range(i-lb, i+lb+1) if j != i):
            highs.append({"price": candles[i]["h"], "idx": i})
        if all(candles[i]["l"] <= candles[j]["l"]
               for j in range(i-lb, i+lb+1) if j != i):
            lows.append({"price": candles[i]["l"], "idx": i})
    return highs, lows

def get_structure(candles, lb=5):
    sh, sl = find_swings(candles, lb)
    if len(sh) < 3 or len(sl) < 3:
        return "NEUTRAL", None, None, 0, 0
    lh, ph = sh[-1]["price"], sh[-2]["price"]
    ll, pl = sl[-1]["price"], sl[-2]["price"]
    price  = candles[-1]["c"]
    if lh > ph and ll > pl:   trend = "BULLISH"
    elif lh < ph and ll < pl: trend = "BEARISH"
    else:                     trend = "NEUTRAL"
    bos = ("BULLISH" if trend=="BULLISH" and price>lh else
           "BEARISH" if trend=="BEARISH" and price<ll else None)
    choch = ("BEARISH_CHOCH" if trend=="BULLISH" and price<pl else
             "BULLISH_CHOCH" if trend=="BEARISH" and price>ph else None)
    return trend, bos, choch, lh, ll

def count_trend_strength(candles):
    """
    شمارش پشت سر هم HH/HL یا LH/LL
    هر چی بیشتر = روند قوی‌تر
    """
    sh, sl = find_swings(candles, lb=4)
    if len(sh) < 4 or len(sl) < 4: return 0, 0
    bull_count = 0
    bear_count = 0
    for i in range(1, min(5, len(sh))):
        if sh[-i]["price"] > sh[-(i+1)]["price"]: bull_count += 1
        else: break
    for i in range(1, min(5, len(sl))):
        if sl[-i]["price"] < sl[-(i+1)]["price"]: bear_count += 1
        else: break
    return bull_count, bear_count

def find_premium_obs(candles):
    """
    Order Block با کیفیت بالا:
    - تنها کندلی که قبل از BOS بود
    - با ایمپالس قوی
    - هنوز میتیگیت نشده
    """
    bull, bear = [], []
    sh, sl = find_swings(candles, lb=3)

    for i in range(5, len(candles)-5):
        c    = candles[i]
        body = abs(c["c"] - c["o"])
        if body == 0: continue

        next5_high = max(candles[j]["h"] for j in range(i+1, min(i+8, len(candles))))
        next5_low  = min(candles[j]["l"] for j in range(i+1, min(i+8, len(candles))))

        # Bullish OB: کندل نزولی + ایمپالس صعودی قوی که BOS ایجاد کرد
        if c["c"] < c["o"] and next5_high > c["h"] * 1.003:
            imp = (next5_high - c["h"]) / body
            if imp > 0.5:
                # چک کن OB هنوز میتیگیت نشده
                future_lows = [candles[j]["l"] for j in range(i+1, len(candles))]
                mitigated = any(fl <= c["o"] for fl in future_lows)
                if not mitigated:
                    bull.append({
                        "top": c["o"], "bottom": c["l"],
                        "mid": (c["o"]+c["l"])/2,
                        "imp": round(imp, 2), "idx": i,
                        "fresh": True
                    })

        # Bearish OB: کندل صعودی + ایمپالس نزولی قوی
        if c["c"] > c["o"] and next5_low < c["l"] * 0.997:
            imp = (c["l"] - next5_low) / body
            if imp > 0.5:
                future_highs = [candles[j]["h"] for j in range(i+1, len(candles))]
                mitigated = any(fh >= c["o"] for fh in future_highs)
                if not mitigated:
                    bear.append({
                        "top": c["h"], "bottom": c["o"],
                        "mid": (c["h"]+c["o"])/2,
                        "imp": round(imp, 2), "idx": i,
                        "fresh": True
                    })

    return bull[-5:], bear[-5:]

def find_breaker_blocks(candles):
    """
    Breaker Block:
    OBی که میتیگیت شد و تبدیل به S/R معکوس شد
    قوی‌ترین نوع OB
    """
    bull_breakers, bear_breakers = [], []
    sh, sl = find_swings(candles, lb=3)

    for i in range(5, len(candles)-10):
        c    = candles[i]
        body = abs(c["c"] - c["o"])
        if body == 0: continue

        # Bullish Breaker: OB نزولی که قیمت ازش رد شد و الان ساپورت شد
        if c["c"] > c["o"]:  # کندل صعودی که OB نزولی بود
            was_resistance = any(
                candles[j]["h"] >= c["bottom"] and candles[j]["c"] < c["bottom"]
                for j in range(i+1, min(i+10, len(candles)))
                if hasattr(c, "bottom")
            )
        # ساده‌تر: بررسی swing که شکسته شد
        for sl_pt in sl:
            if sl_pt["idx"] > i and sl_pt["price"] < c["l"]:
                # این low شکسته شد - اگه الان قیمت برگشت = bullish breaker
                current_price = candles[-1]["c"]
                if current_price > c["l"] and c["l"] <= current_price <= c["h"]:
                    bull_breakers.append({
                        "top": c["h"], "bottom": c["l"],
                        "mid": (c["h"]+c["l"])/2, "idx": i
                    })
                break

    return bull_breakers[-2:], bear_breakers[-2:]

def find_fvg(candles, min_size_atr=0.1):
    """
    FVG با فیلتر اندازه - فقط FVGهای با اهمیت
    """
    bull, bear = [], []
    atr = calc_atr(candles)
    min_size = atr * min_size_atr

    for i in range(len(candles)-2):
        c1, c2, c3 = candles[i], candles[i+1], candles[i+2]

        # Bullish FVG
        if c3["l"] > c1["h"]:
            size = c3["l"] - c1["h"]
            if size >= min_size:
                # چک کن پر نشده
                future_lows = [candles[j]["l"] for j in range(i+2, len(candles))]
                filled = any(fl <= c1["h"] for fl in future_lows)
                bull.append({
                    "top": c3["l"], "bottom": c1["h"],
                    "mid": (c3["l"]+c1["h"])/2,
                    "size": round(size,8),
                    "filled": filled, "idx": i+1
                })

        # Bearish FVG
        if c3["h"] < c1["l"]:
            size = c1["l"] - c3["h"]
            if size >= min_size:
                future_highs = [candles[j]["h"] for j in range(i+2, len(candles))]
                filled = any(fh >= c1["l"] for fh in future_highs)
                bear.append({
                    "top": c1["l"], "bottom": c3["h"],
                    "mid": (c1["l"]+c3["h"])/2,
                    "size": round(size,8),
                    "filled": filled, "idx": i+1
                })

    # فقط unfilled برگردون
    bull = [f for f in bull if not f["filled"]][-5:]
    bear = [f for f in bear if not f["filled"]][-5:]
    return bull, bear

def find_liquidity(candles):
    """
    Equal Highs/Lows با دقت بالا
    + Previous Day High/Low (PDH/PDL)
    """
    highs = [c["h"] for c in candles[-80:]]
    lows  = [c["l"] for c in candles[-80:]]
    bsl, ssl = [], []
    tol = 0.0012

    for i in range(len(highs)):
        for j in range(i+5, len(highs)):
            if not highs[i]: continue
            if abs(highs[i]-highs[j])/highs[i] < tol:
                lvl = (highs[i]+highs[j])/2
                if not any(abs(z-lvl)/lvl < tol for z in bsl):
                    bsl.append(lvl)

    for i in range(len(lows)):
        for j in range(i+5, len(lows)):
            if not lows[i]: continue
            if abs(lows[i]-lows[j])/lows[i] < tol:
                lvl = (lows[i]+lows[j])/2
                if not any(abs(z-lvl)/lvl < tol for z in ssl):
                    ssl.append(lvl)

    # اضافه کردن previous swing highs/lows به عنوان liquidity
    sh, sl = find_swings(candles[-80:], lb=8)
    for s in sh[-3:]:
        if not any(abs(s["price"]-z)/s["price"] < tol for z in bsl):
            bsl.append(s["price"])
    for s in sl[-3:]:
        if not any(abs(s["price"]-z)/s["price"] < tol for z in ssl):
            ssl.append(s["price"])

    return sorted(bsl)[-5:], sorted(ssl)[:5]

def detect_manipulation(candles):
    """
    تشخیص Manipulation (Judas Swing):
    حرکت فیک در یه جهت قبل از حرکت اصلی
    مهمترین مفهوم ICT
    """
    if len(candles) < 10: return None
    recent = candles[-8:]
    price = candles[-1]["c"]

    # بررسی spike و برگشت سریع
    for i in range(1, len(recent)-2):
        c = recent[i]
        prev_close = recent[i-1]["c"]
        next_close = recent[i+2]["c"]
        spike_up   = c["h"] - max(c["o"], c["c"])
        spike_down = min(c["o"], c["c"]) - c["l"]
        body       = abs(c["c"] - c["o"])

        # Bearish manipulation: spike بالا + برگشت پایین
        if spike_up > body * 1.5 and next_close < prev_close:
            return "BEARISH_MANIP"

        # Bullish manipulation: spike پایین + برگشت بالا
        if spike_down > body * 1.5 and next_close > prev_close:
            return "BULLISH_MANIP"

    return None

def get_session():
    h = datetime.now(timezone.utc).hour
    if 7  <= h < 10: return "LONDON OPEN 🇬🇧", 15
    if 10 <= h < 12: return "LONDON 🇬🇧", 10
    if 12 <= h < 16: return "NY OPEN 🗽", 15
    if 16 <= h < 20: return "NEW YORK 🗽", 10
    if 0  <= h < 7:  return "ASIAN 🌏", 3
    return "OVERLAP", 5

def detect_candlestick_pattern(candles):
    """
    پترن‌های مهم کندلی برای تأیید
    """
    if len(candles) < 3: return None
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]

    # Engulfing صعودی
    if (c2["c"] < c2["o"] and c3["c"] > c3["o"] and
            c3["c"] > c2["o"] and c3["o"] < c2["c"]):
        return "BULLISH_ENGULF"

    # Engulfing نزولی
    if (c2["c"] > c2["o"] and c3["c"] < c3["o"] and
            c3["c"] < c2["o"] and c3["o"] > c2["c"]):
        return "BEARISH_ENGULF"

    # Pin Bar صعودی (hammer)
    body  = abs(c3["c"] - c3["o"])
    range_ = c3["h"] - c3["l"]
    if range_ > 0:
        lower_wick = min(c3["o"],c3["c"]) - c3["l"]
        upper_wick = c3["h"] - max(c3["o"],c3["c"])
        if lower_wick > body*2 and lower_wick > upper_wick*2:
            return "BULLISH_PIN"
        if upper_wick > body*2 and upper_wick > lower_wick*2:
            return "BEARISH_PIN"

    return None

# ══════════════════════════════════
#  MAIN ANALYSIS ENGINE
# ══════════════════════════════════

def analyze(symbol):
    # دریافت داده با کندل بیشتر برای دقت
    htf = get_klines(symbol, HTF, 300)
    itf = get_klines(symbol, ITF, 300)
    ltf = get_klines(symbol, LTF, 150)

    if len(htf)<80 or len(itf)<80 or len(ltf)<30:
        return None

    price = ltf[-1]["c"]
    atr   = calc_atr(ltf)
    if not price or not atr: return None

    # ── ساختار ۳ تایم‌فریم ──
    htf_t, htf_bos, htf_ch, htf_lh, htf_ll = get_structure(htf, lb=8)
    itf_t, itf_bos, itf_ch, itf_lh, itf_ll = get_structure(itf, lb=5)
    ltf_t, ltf_bos, ltf_ch, ltf_lh, ltf_ll = get_structure(ltf, lb=3)

    # ── قدرت روند ──
    bull_strength, bear_strength = count_trend_strength(htf)

    # ── OB, FVG, Liquidity ──
    bull_ob, bear_ob     = find_premium_obs(itf)
    bull_fvg, bear_fvg   = find_fvg(itf)
    bsl, ssl             = find_liquidity(itf)
    sh_ltf, sl_ltf       = find_swings(ltf, lb=3)

    # ── اندیکاتورهای تکمیلی ──
    rsi_htf  = calc_rsi(htf)
    rsi_itf  = calc_rsi(itf)
    rsi_ltf  = calc_rsi(ltf)
    rsi_ser  = calc_rsi_series(ltf)
    ema20    = calc_ema(ltf, 20)
    ema50    = calc_ema(ltf, 50)
    ema200   = calc_ema(htf, 200)
    vol_d    = calc_volume_delta(ltf)
    vol_r    = calc_avg_vol(ltf)
    div      = detect_divergence(ltf, rsi_ser)
    manip    = detect_manipulation(ltf)
    candle_p = detect_candlestick_pattern(ltf)
    session, sess_pts = get_session()

    best = None

    for d in ["LONG", "SHORT"]:
        score = 0
        conf  = 0  # تعداد تأییدیه‌های اصلی

        # ══ لایه ۱: HTF Bias - پایه اصلی (اجباری) ══
        htf_aligned = (d=="LONG" and htf_t=="BULLISH") or \
                      (d=="SHORT" and htf_t=="BEARISH")
        if htf_aligned:
            score += 20
            conf  += 1
            # قدرت روند HTF
            if d=="LONG"  and bull_strength >= 3: score += 10
            elif d=="SHORT" and bear_strength >= 3: score += 10
        elif htf_t == "NEUTRAL":
            score += 0  # خنثی = بی‌امتیاز
        else:
            score -= 25  # خلاف روند = جریمه سنگین

        # ══ لایه ۲: EMA 200 HTF ══
        htf_price = htf[-1]["c"]
        if d=="LONG"  and htf_price > ema200: score += 8
        elif d=="SHORT" and htf_price < ema200: score += 8

        # ══ لایه ۳: ITF Confirmation ══
        itf_aligned = (d=="LONG" and itf_t in ["BULLISH","NEUTRAL"]) or \
                      (d=="SHORT" and itf_t in ["BEARISH","NEUTRAL"])
        if itf_aligned: score += 12; conf += 1
        else:           score -= 10

        # ══ لایه ۴: CHoCH - مهمترین سیگنال ورود ══
        if d == "LONG":
            if ltf_ch == "BULLISH_CHOCH":
                score += 25; conf += 2  # دو تأییدیه
            elif itf_ch == "BULLISH_CHOCH":
                score += 18; conf += 1
            elif ltf_bos == "BULLISH":
                score += 10; conf += 1
            elif itf_bos == "BULLISH":
                score += 6
        else:
            if ltf_ch == "BEARISH_CHOCH":
                score += 25; conf += 2
            elif itf_ch == "BEARISH_CHOCH":
                score += 18; conf += 1
            elif ltf_bos == "BEARISH":
                score += 10; conf += 1
            elif itf_bos == "BEARISH":
                score += 6

        # ══ لایه ۵: Order Block Premium ══
        ob_hit = False
        if d == "LONG":
            for ob in reversed(bull_ob):
                if ob["bottom"]*0.997 <= price <= ob["top"]*1.003:
                    pts = min(20, int(12 + ob["imp"]*3))
                    score += pts; conf += 1; ob_hit = True; break
        else:
            for ob in reversed(bear_ob):
                if ob["bottom"]*0.997 <= price <= ob["top"]*1.003:
                    pts = min(20, int(12 + ob["imp"]*3))
                    score += pts; conf += 1; ob_hit = True; break

        # ══ لایه ۶: Fair Value Gap (Unfilled) ══
        fvg_hit = False
        if d == "LONG":
            for fvg in reversed(bull_fvg):
                if fvg["bottom"] <= price <= fvg["top"]:
                    score += 15; conf += 1; fvg_hit = True; break
        else:
            for fvg in reversed(bear_fvg):
                if fvg["bottom"] <= price <= fvg["top"]:
                    score += 15; conf += 1; fvg_hit = True; break

        # ══ لایه ۷: Liquidity Sweep ══
        swept = False
        if d == "LONG":
            for lvl in ssl:
                if ltf[-1]["l"] < lvl * 1.002 and price > lvl:
                    score += 18; conf += 1; swept = True; break
        else:
            for lvl in bsl:
                if ltf[-1]["h"] > lvl * 0.998 and price < lvl:
                    score += 18; conf += 1; swept = True; break

        # ══ لایه ۸: RSI Multi-TF ══
        if d == "LONG":
            if rsi_ltf < 30 and rsi_itf < 40:
                score += 12; conf += 1  # اشباع فروش دوتایم‌فریم
            elif rsi_ltf < 45 and rsi_htf > 50:
                score += 6
            if rsi_ltf > 70:  # خلاف = جریمه
                score -= 12
        else:
            if rsi_ltf > 70 and rsi_itf > 60:
                score += 12; conf += 1
            elif rsi_ltf > 55 and rsi_htf < 50:
                score += 6
            if rsi_ltf < 30:
                score -= 12

        # ══ لایه ۹: EMA LTF ══
        if d=="LONG"  and price > ema20 > ema50: score += 8
        elif d=="SHORT" and price < ema20 < ema50: score += 8

        # ══ لایه ۱۰: Volume Delta ══
        if d=="LONG"  and vol_d > 0.55: score += 10; conf += 1
        elif d=="SHORT" and vol_d < 0.45: score += 10; conf += 1
        elif d=="LONG"  and vol_d < 0.40: score -= 8
        elif d=="SHORT" and vol_d > 0.60: score -= 8

        # ══ لایه ۱۱: Volume Spike ══
        if vol_r > 1.5: score += 8
        elif vol_r < 0.5: score -= 6

        # ══ لایه ۱۲: Divergence ══
        if d=="LONG"  and div == "BULLISH_DIV": score += 15; conf += 1
        elif d=="SHORT" and div == "BEARISH_DIV": score += 15; conf += 1

        # ══ لایه ۱۳: Manipulation Detection ══
        if d=="LONG"  and manip == "BULLISH_MANIP": score += 15; conf += 1
        elif d=="SHORT" and manip == "BEARISH_MANIP": score += 15; conf += 1

        # ══ لایه ۱۴: Candlestick Pattern ══
        if d=="LONG"  and candle_p in ["BULLISH_ENGULF","BULLISH_PIN"]:
            score += 10; conf += 1
        elif d=="SHORT" and candle_p in ["BEARISH_ENGULF","BEARISH_PIN"]:
            score += 10; conf += 1

        # ══ لایه ۱۵: Session ══
        score += sess_pts

        # ── فیلترهای سخت ──
        # حداقل ۳ تأییدیه اصلی لازمه
        if conf < 3: continue
        # حداقل یکی از OB/FVG/Sweep باید باشه
        if not (ob_hit or fvg_hit or swept): continue
        # HTF کاملاً مخالف نباشه
        if score < 70: continue

        # ── محاسبه SL/TP هوشمند ──
        if d == "LONG":
            # SL زیر آخرین Swing Low + کمی پایین‌تر
            sl_base = sl_ltf[-1]["price"] if sl_ltf else price - atr*2
            sl_p = round(min(sl_base * 0.9985, price - atr*1.0), 8)

            tp1 = round(price + (price-sl_p)*1.5, 8)

            # TP2 روی نزدیک‌ترین BSL بالای قیمت (نقدینگی هدف)
            nb  = min((l for l in bsl if l > price*1.001), default=None)
            tp2 = round(nb if nb else price + (price-sl_p)*3.5, 8)

        else:
            sh_base = sh_ltf[-1]["price"] if sh_ltf else price + atr*2
            sl_p = round(max(sh_base * 1.0015, price + atr*1.0), 8)

            tp1 = round(price - (sl_p-price)*1.5, 8)

            ns  = max((l for l in ssl if l < price*0.999), default=None)
            tp2 = round(ns if ns else price - (sl_p-price)*3.5, 8)

        dist = abs(price - sl_p)
        rr   = round(abs(tp2-price)/dist, 1) if dist > 0 else 0

        # R:R حداقل ۲
        if rr < 2.0: continue

        sl_pct  = round(dist/price*100, 2)
        tp1_pct = round(abs(tp1-price)/price*100, 2)
        tp2_pct = round(abs(tp2-price)/price*100, 2)

        res = {
            "symbol": symbol, "direction": d,
            "score": score, "conf": conf,
            "price": round(price,8),
            "sl": sl_p, "tp1": tp1, "tp2": tp2,
            "rr": rr,
            "sl_pct": sl_pct, "tp1_pct": tp1_pct, "tp2_pct": tp2_pct,
            "session": session,
        }

        if best is None or score > best["score"]:
            best = res

    return best

# ══════════════════════════════════
#  FORMAT
# ══════════════════════════════════

def format_signal(s, rank):
    sym  = s["symbol"].replace("-", "/")
    icon = "📈" if s["direction"] == "LONG" else "📉"
    ri   = "🥇" if rank==1 else ("🥈" if rank==2 else "🥉")
    side = "LONG  🟢" if s["direction"] == "LONG" else "SHORT 🔴"
    conf = min(99, int(s["score"] * 0.97))

    return (f"{ri} {icon} #{rank} SIGNAL  |  {conf}% Confidence\n\n"
            f"🪙 {sym}\n"
            f"📊 {side}\n"
            f"⏰ {s['session']}\n"
            f"{'━'*26}\n"
            f"💰 ENTRY:  {s['price']}\n"
            f"🛑 SL:     {s['sl']}  (-{s['sl_pct']}%)\n"
            f"🎯 TP1:    {s['tp1']}  (+{s['tp1_pct']}%)\n"
            f"🎯 TP2:    {s['tp2']}  (+{s['tp2_pct']}%)\n"
            f"📐 R:R     1:{s['rr']}")

def format_open(pos, rank):
    sym  = pos["symbol"].replace("-", "/")
    icon = "📈" if pos["direction"] == "LONG" else "📉"
    ri   = "🥇" if rank==1 else ("🥈" if rank==2 else "🥉")
    side = "LONG  🟢" if pos["direction"] == "LONG" else "SHORT 🔴"

    return (f"{ri} {icon} OPEN POSITION\n\n"
            f"🪙 {sym}\n"
            f"📊 {side}\n"
            f"{'━'*26}\n"
            f"💰 ENTRY:  {pos['entry']}\n"
            f"🛑 SL:     {pos['sl']}\n"
            f"🎯 TP1:    {pos['tp1']}\n"
            f"🎯 TP2:    {pos['tp2']}")

# ══════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════

def send_tg(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10)
        return r.json().get("ok", False)
    except:
        return False

def send_sticker(sid):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendSticker",
            json={"chat_id": TELEGRAM_CHAT_ID, "sticker": sid},
            timeout=10)
    except:
        pass

STICKER_SIGNAL = "CAACAgIAAxkBAAIBhWX6AAGSJwABhBKNpMoAAWVlE6UZAAJ4AQACB8xhS5mHETfIBCFhHgQ"
STICKER_WIN    = "CAACAgIAAxkBAAIBiWX6AAGWJwABhBKNpMoAAWVlE6UZAAJ5AQACB8xhS5mHETfIBCFhHgQ"
STICKER_LOSS   = "CAACAgIAAxkBAAIBi2X6AAGYJwABhBKNpMoAAWVlE6UZAAJ6AQACB8xhS5mHETfIBCFhHgQ"

# ══════════════════════════════════
#  MAIN
# ══════════════════════════════════

def main():
    if not TELEGRAM_TOKEN:
        print("No token!"); return

    state = load_state()
    print(f"Open positions: {len(state['open'])}")

    # ── چک پوزیشن‌های باز ──
    for key in list(state["open"].keys()):
        pos = state["open"].get(key)
        if not pos: continue
        ltf = get_klines(pos["symbol"], LTF, 5)
        if not ltf: continue
        cp = ltf[-1]["c"]
        for p, result in check_closed(state, pos["symbol"], cp):
            if result == "SL":
                send_sticker(STICKER_LOSS)
                send_tg(f"❌ SL HIT\n"
                        f"{p['symbol'].replace('-','/')} {p['direction']}\n"
                        f"Entry: {p['entry']}  →  Exit: {cp}")
            else:
                send_sticker(STICKER_WIN)
                send_tg(f"✅ TP2 HIT\n"
                        f"{p['symbol'].replace('-','/')} {p['direction']}\n"
                        f"Entry: {p['entry']}  →  Exit: {cp}")
        time.sleep(0.5)

    # ── اگه پوزیشن باز داریم فقط همونا رو بفرست ──
    open_positions = list(state["open"].values())
    if open_positions:
        send_sticker(STICKER_SIGNAL)
        time.sleep(0.3)
        for i, pos in enumerate(open_positions[:3], 1):
            send_tg(format_open(pos, i))
            time.sleep(0.8)
        print(f"Sent {len(open_positions)} open positions")
        return

    # ── اسکن همه ارزها ──
    print(f"Scanning {len(SYMBOLS)} symbols...")
    candidates = []

    for symbol in SYMBOLS:
        print(f"  {symbol}...", end=" ", flush=True)
        try:
            sig = analyze(symbol)
            if sig:
                candidates.append(sig)
                print(f"✓ {sig['direction']} sc:{sig['score']} cf:{sig['conf']}")
            else:
                print("no")
            time.sleep(1.0)
        except Exception as e:
            print(f"err:{e}"); time.sleep(1)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:3]

    if top:
        send_sticker(STICKER_SIGNAL)
        time.sleep(0.3)
        for i, sig in enumerate(top, 1):
            msg = format_signal(sig, i)
            sig["msg"] = msg
            if send_tg(msg):
                add_position(state, sig)
            time.sleep(0.8)
        print(f"Sent {len(top)} signals")
    else:
        now = datetime.now(timezone.utc).strftime("%H:%M")
        send_tg(f"🔍 {len(SYMBOLS)} pairs scanned\n"
                f"❌ No quality signals found\n"
                f"🕐 {now} UTC")
        print("No signals")

if __name__ == "__main__":
    main()
