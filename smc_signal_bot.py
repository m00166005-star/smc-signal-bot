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
    "STX-USDT","RUNE-USDT","FET-USDT","WLD-USDT","TIA-USDT",
    "PEPE-USDT","FLOKI-USDT","BONK-USDT","SEI-USDT","JTO-USDT",
    "PYTH-USDT","JUP-USDT","ONDO-USDT","ENA-USDT","ETHFI-USDT",
    "W-USDT","SAFE-USDT","ALT-USDT","DYM-USDT","MANTA-USDT",
    "PIXEL-USDT","PORTAL-USDT","STRK-USDT","ZETA-USDT","OMNI-USDT"
]

BASE_URL = "https://api.kucoin.com"
HTF, ITF, LTF = "1hour", "15min", "5min"
MAX_POSITION_HOURS = 4

# ══════════════════════════════════
#  STATE
# ══════════════════════════════════

def load_state():
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"limit": 100, "offset": -100}, timeout=10)
        for m in reversed(r.json().get("result", [])):
            text = m.get("message", {}).get("text", "")
            if text.startswith("__STATE__:"):
                return json.loads(text[10:])
    except: pass
    return {"open": {}}

def save_state(state):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID,
                  "text": f"__STATE__:{json.dumps(state)}",
                  "disable_notification": True}, timeout=10)
    except: pass

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
        "open_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    }
    save_state(state)

def hours_open(pos):
    try:
        t = datetime.strptime(pos["open_time"], "%Y-%m-%d %H:%M")
        t = t.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - t
        return diff.total_seconds() / 3600
    except: return 0

def check_closed(state, symbol, price):
    closed = []
    to_del = []
    for key, p in list(state["open"].items()):
        if p["symbol"] != symbol: continue
        if p["direction"] == "LONG":
            if price <= p["sl"]:   closed.append((p,"SL")); to_del.append(key)
            elif price >= p["tp2"]: closed.append((p,"TP2")); to_del.append(key)
            elif price >= p["tp1"]: state["open"][key]["sl"] = p["entry"]
        else:
            if price >= p["sl"]:   closed.append((p,"SL")); to_del.append(key)
            elif price <= p["tp2"]: closed.append((p,"TP2")); to_del.append(key)
            elif price <= p["tp1"]: state["open"][key]["sl"] = p["entry"]
    for k in to_del: del state["open"][k]
    if to_del: save_state(state)
    return closed

# ══════════════════════════════════
#  DATA
# ══════════════════════════════════

def get_klines(symbol, interval, limit=300):
    try:
        r = requests.get(f"{BASE_URL}/api/v1/market/candles",
                         params={"symbol": symbol, "type": interval}, timeout=10)
        raw = r.json().get("data", [])[:limit]
        return [{"o":float(d[1]),"c":float(d[2]),
                 "h":float(d[3]),"l":float(d[4]),"v":float(d[5])}
                for d in reversed(raw)]
    except: return []

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

def calc_volume_delta(candles, lb=20):
    recent = candles[-lb:]
    buy  = sum(c["v"] for c in recent if c["c"] >= c["o"])
    sell = sum(c["v"] for c in recent if c["c"] < c["o"])
    t = buy + sell
    return round(buy/t, 3) if t else 0.5

def calc_avg_vol(candles, p=20):
    avg = sum(c["v"] for c in candles[-p-1:-1]) / p
    return round(candles[-1]["v"]/avg, 2) if avg else 1

def calc_rsi_series(candles, p=14):
    closes = [c["c"] for c in candles]
    if len(closes) < p+2: return []
    series = []
    for i in range(p+1, len(closes)):
        sub = closes[:i+1]
        g = [max(sub[j]-sub[j-1],0) for j in range(1,len(sub))]
        l = [max(sub[j-1]-sub[j],0) for j in range(1,len(sub))]
        ag = sum(g[-p:])/p; al = sum(l[-p:])/p
        series.append(round(100-(100/(1+ag/al)),1) if al else 100)
    return series

def detect_divergence(candles, rsi_vals, lb=10):
    if len(candles)<lb or len(rsi_vals)<lb: return None
    prices = [c["c"] for c in candles[-lb:]]
    rsis   = rsi_vals[-lb:]
    if prices[-1] < prices[0] and rsis[-1] > rsis[0]: return "BULLISH_DIV"
    if prices[-1] > prices[0] and rsis[-1] < rsis[0]: return "BEARISH_DIV"
    return None

def detect_manipulation(candles):
    if len(candles) < 8: return None
    recent = candles[-8:]
    for i in range(1, len(recent)-2):
        c = recent[i]
        body = abs(c["c"]-c["o"])
        spike_up   = c["h"] - max(c["o"],c["c"])
        spike_down = min(c["o"],c["c"]) - c["l"]
        if spike_up > body*1.5 and recent[i+2]["c"] < recent[i-1]["c"]:
            return "BEARISH_MANIP"
        if spike_down > body*1.5 and recent[i+2]["c"] > recent[i-1]["c"]:
            return "BULLISH_MANIP"
    return None

def detect_candle_pattern(candles):
    if len(candles) < 3: return None
    c1,c2,c3 = candles[-3],candles[-2],candles[-1]
    if (c2["c"]<c2["o"] and c3["c"]>c3["o"] and
            c3["c"]>c2["o"] and c3["o"]<c2["c"]): return "BULLISH_ENGULF"
    if (c2["c"]>c2["o"] and c3["c"]<c3["o"] and
            c3["c"]<c2["o"] and c3["o"]>c2["c"]): return "BEARISH_ENGULF"
    body  = abs(c3["c"]-c3["o"])
    rng   = c3["h"]-c3["l"]
    if rng > 0:
        lw = min(c3["o"],c3["c"])-c3["l"]
        uw = c3["h"]-max(c3["o"],c3["c"])
        if lw > body*2 and lw > uw*2: return "BULLISH_PIN"
        if uw > body*2 and uw > lw*2: return "BEARISH_PIN"
    return None

# ══════════════════════════════════
#  PRICE ACTION
# ══════════════════════════════════

def find_swings(candles, lb=5):
    highs, lows = [], []
    for i in range(lb, len(candles)-lb):
        if all(candles[i]["h"] >= candles[j]["h"]
               for j in range(i-lb,i+lb+1) if j!=i):
            highs.append({"price":candles[i]["h"],"idx":i})
        if all(candles[i]["l"] <= candles[j]["l"]
               for j in range(i-lb,i+lb+1) if j!=i):
            lows.append({"price":candles[i]["l"],"idx":i})
    return highs, lows

def get_structure(candles, lb=5):
    sh, sl = find_swings(candles, lb)
    if len(sh)<3 or len(sl)<3: return "NEUTRAL",None,None,0,0
    lh,ph = sh[-1]["price"],sh[-2]["price"]
    ll,pl = sl[-1]["price"],sl[-2]["price"]
    price = candles[-1]["c"]
    if lh>ph and ll>pl:     trend="BULLISH"
    elif lh<ph and ll<pl:   trend="BEARISH"
    else:                   trend="NEUTRAL"
    bos = ("BULLISH" if trend=="BULLISH" and price>lh else
           "BEARISH" if trend=="BEARISH" and price<ll else None)
    choch = ("BEARISH_CHOCH" if trend=="BULLISH" and price<pl else
             "BULLISH_CHOCH" if trend=="BEARISH" and price>ph else None)
    return trend, bos, choch, lh, ll

def count_trend_strength(candles):
    sh, sl = find_swings(candles, lb=4)
    if len(sh)<4 or len(sl)<4: return 0,0
    bc = sum(1 for i in range(1,min(5,len(sh))) if sh[-i]["price"]>sh[-(i+1)]["price"])
    dc = sum(1 for i in range(1,min(5,len(sl))) if sl[-i]["price"]<sl[-(i+1)]["price"])
    return bc, dc

def find_obs(candles):
    bull, bear = [], []
    for i in range(5, len(candles)-5):
        c = candles[i]
        body = abs(c["c"]-c["o"])
        if not body: continue
        fh = max(candles[j]["h"] for j in range(i+1,min(i+8,len(candles))))
        fl = min(candles[j]["l"] for j in range(i+1,min(i+8,len(candles))))
        if c["c"]<c["o"] and fh>c["h"]*1.003:
            imp = (fh-c["h"])/body
            if imp>0.5:
                future_lows = [candles[j]["l"] for j in range(i+1,len(candles))]
                if not any(fl<=c["o"] for fl in future_lows):
                    bull.append({"top":c["o"],"bottom":c["l"],"imp":round(imp,2)})
        if c["c"]>c["o"] and fl<c["l"]*0.997:
            imp = (c["l"]-fl)/body
            if imp>0.5:
                future_highs = [candles[j]["h"] for j in range(i+1,len(candles))]
                if not any(fh>=c["o"] for fh in future_highs):
                    bear.append({"top":c["h"],"bottom":c["o"],"imp":round(imp,2)})
    return bull[-5:], bear[-5:]

def find_fvg(candles):
    bull, bear = [], []
    atr = calc_atr(candles)
    ms  = atr * 0.1
    for i in range(len(candles)-2):
        c1,c3 = candles[i],candles[i+2]
        if c3["l"]>c1["h"] and (c3["l"]-c1["h"])>=ms:
            fl = [candles[j]["l"] for j in range(i+2,len(candles))]
            if not any(x<=c1["h"] for x in fl):
                bull.append({"top":c3["l"],"bottom":c1["h"]})
        if c3["h"]<c1["l"] and (c1["l"]-c3["h"])>=ms:
            fh = [candles[j]["h"] for j in range(i+2,len(candles))]
            if not any(x>=c1["l"] for x in fh):
                bear.append({"top":c1["l"],"bottom":c3["h"]})
    return bull[-5:], bear[-5:]

def find_liquidity(candles):
    highs = [c["h"] for c in candles[-80:]]
    lows  = [c["l"] for c in candles[-80:]]
    bsl,ssl = [],[]
    tol = 0.0012
    for i in range(len(highs)):
        for j in range(i+5,len(highs)):
            if not highs[i]: continue
            if abs(highs[i]-highs[j])/highs[i]<tol:
                lvl=(highs[i]+highs[j])/2
                if not any(abs(z-lvl)/lvl<tol for z in bsl): bsl.append(lvl)
    for i in range(len(lows)):
        for j in range(i+5,len(lows)):
            if not lows[i]: continue
            if abs(lows[i]-lows[j])/lows[i]<tol:
                lvl=(lows[i]+lows[j])/2
                if not any(abs(z-lvl)/lvl<tol for z in ssl): ssl.append(lvl)
    sh,sl = find_swings(candles[-80:],lb=8)
    for s in sh[-3:]:
        if not any(abs(s["price"]-z)/s["price"]<tol for z in bsl): bsl.append(s["price"])
    for s in sl[-3:]:
        if not any(abs(s["price"]-z)/s["price"]<tol for z in ssl): ssl.append(s["price"])
    return sorted(bsl)[-5:], sorted(ssl)[:5]

def get_session():
    h = datetime.now(timezone.utc).hour
    if 7<=h<10:   return "LONDON OPEN 🇬🇧", 15
    if 10<=h<12:  return "LONDON 🇬🇧", 10
    if 12<=h<16:  return "NY OPEN 🗽", 15
    if 16<=h<20:  return "NEW YORK 🗽", 10
    if 0<=h<7:    return "ASIAN 🌏", 3
    return "OVERLAP", 5

# ══════════════════════════════════
#  ANALYZE
# ══════════════════════════════════

def analyze(symbol):
    htf = get_klines(symbol, HTF, 300)
    itf = get_klines(symbol, ITF, 300)
    ltf = get_klines(symbol, LTF, 150)
    if len(htf)<80 or len(itf)<80 or len(ltf)<30: return None

    price = ltf[-1]["c"]
    atr   = calc_atr(ltf)
    if not price or not atr: return None

    htf_t,htf_bos,htf_ch,htf_lh,htf_ll = get_structure(htf,lb=8)
    itf_t,itf_bos,itf_ch,itf_lh,itf_ll = get_structure(itf,lb=5)
    ltf_t,ltf_bos,ltf_ch,ltf_lh,ltf_ll = get_structure(ltf,lb=3)

    bull_str, bear_str = count_trend_strength(htf)
    bull_ob, bear_ob   = find_obs(itf)
    bull_fvg,bear_fvg  = find_fvg(itf)
    bsl, ssl           = find_liquidity(itf)
    sh_ltf, sl_ltf     = find_swings(ltf,lb=3)

    rsi_htf = calc_rsi(htf)
    rsi_itf = calc_rsi(itf)
    rsi_ltf_val = calc_rsi(ltf)
    rsi_ser = calc_rsi_series(ltf)
    ema20   = calc_ema(ltf,20)
    ema50   = calc_ema(ltf,50)
    ema200  = calc_ema(htf,200)
    vol_d   = calc_volume_delta(ltf)
    vol_r   = calc_avg_vol(ltf)
    div     = detect_divergence(ltf,rsi_ser)
    manip   = detect_manipulation(ltf)
    candle  = detect_candle_pattern(ltf)
    session, sess_pts = get_session()

    best = None

    for d in ["LONG","SHORT"]:
        score = 0
        conf  = 0

        # HTF
        htf_ok = (d=="LONG" and htf_t=="BULLISH") or (d=="SHORT" and htf_t=="BEARISH")
        if htf_ok:
            score += 20; conf += 1
            if d=="LONG"  and bull_str>=3: score+=10
            elif d=="SHORT" and bear_str>=3: score+=10
        elif htf_t!="NEUTRAL": score -= 25

        # EMA200
        if d=="LONG"  and htf[-1]["c"]>ema200: score+=8
        elif d=="SHORT" and htf[-1]["c"]<ema200: score+=8

        # ITF
        itf_ok = (d=="LONG" and itf_t in ["BULLISH","NEUTRAL"]) or \
                 (d=="SHORT" and itf_t in ["BEARISH","NEUTRAL"])
        if itf_ok: score+=12; conf+=1
        else: score-=10

        # CHoCH/BOS
        if d=="LONG":
            if   ltf_ch=="BULLISH_CHOCH": score+=25; conf+=2
            elif itf_ch=="BULLISH_CHOCH": score+=18; conf+=1
            elif ltf_bos=="BULLISH":      score+=10; conf+=1
            elif itf_bos=="BULLISH":      score+=6
        else:
            if   ltf_ch=="BEARISH_CHOCH": score+=25; conf+=2
            elif itf_ch=="BEARISH_CHOCH": score+=18; conf+=1
            elif ltf_bos=="BEARISH":      score+=10; conf+=1
            elif itf_bos=="BEARISH":      score+=6

        # OB
        ob_hit = False
        if d=="LONG":
            for ob in reversed(bull_ob):
                if ob["bottom"]*0.997<=price<=ob["top"]*1.003:
                    score+=min(20,int(12+ob["imp"]*3)); conf+=1; ob_hit=True; break
        else:
            for ob in reversed(bear_ob):
                if ob["bottom"]*0.997<=price<=ob["top"]*1.003:
                    score+=min(20,int(12+ob["imp"]*3)); conf+=1; ob_hit=True; break

        # FVG
        fvg_hit = False
        if d=="LONG":
            for fvg in reversed(bull_fvg):
                if fvg["bottom"]<=price<=fvg["top"]:
                    score+=15; conf+=1; fvg_hit=True; break
        else:
            for fvg in reversed(bear_fvg):
                if fvg["bottom"]<=price<=fvg["top"]:
                    score+=15; conf+=1; fvg_hit=True; break

        # Liquidity Sweep
        swept = False
        if d=="LONG":
            for lvl in ssl:
                if ltf[-1]["l"]<lvl*1.002 and price>lvl:
                    score+=18; conf+=1; swept=True; break
        else:
            for lvl in bsl:
                if ltf[-1]["h"]>lvl*0.998 and price<lvl:
                    score+=18; conf+=1; swept=True; break

        # RSI
        if d=="LONG":
            if rsi_ltf_val<30 and rsi_itf<40: score+=12; conf+=1
            elif rsi_ltf_val<45 and rsi_htf>50: score+=6
            if rsi_ltf_val>70: score-=12
        else:
            if rsi_ltf_val>70 and rsi_itf>60: score+=12; conf+=1
            elif rsi_ltf_val>55 and rsi_htf<50: score+=6
            if rsi_ltf_val<30: score-=12

        # EMA LTF
        if d=="LONG"  and price>ema20>ema50: score+=8
        elif d=="SHORT" and price<ema20<ema50: score+=8

        # Volume Delta
        if d=="LONG"  and vol_d>0.55: score+=10; conf+=1
        elif d=="SHORT" and vol_d<0.45: score+=10; conf+=1
        elif d=="LONG"  and vol_d<0.40: score-=8
        elif d=="SHORT" and vol_d>0.60: score-=8

        # Volume Spike
        if vol_r>1.5: score+=8
        elif vol_r<0.5: score-=6

        # Divergence
        if d=="LONG"  and div=="BULLISH_DIV": score+=15; conf+=1
        elif d=="SHORT" and div=="BEARISH_DIV": score+=15; conf+=1

        # Manipulation
        if d=="LONG"  and manip=="BULLISH_MANIP": score+=15; conf+=1
        elif d=="SHORT" and manip=="BEARISH_MANIP": score+=15; conf+=1

        # Candle Pattern
        if d=="LONG"  and candle in ["BULLISH_ENGULF","BULLISH_PIN"]: score+=10; conf+=1
        elif d=="SHORT" and candle in ["BEARISH_ENGULF","BEARISH_PIN"]: score+=10; conf+=1

        # Session
        score += sess_pts

        # فیلترها
        if conf<3: continue
        if not (ob_hit or fvg_hit or swept): continue
        if score<70: continue

        # SL/TP
        if d=="LONG":
            sl_base = sl_ltf[-1]["price"] if sl_ltf else price-atr*2
            sl_p = round(min(sl_base*0.9985, price-atr), 8)
            tp1  = round(price+(price-sl_p)*1.5, 8)
            nb   = min((l for l in bsl if l>price*1.001), default=None)
            tp2  = round(nb if nb else price+(price-sl_p)*3.5, 8)
        else:
            sh_base = sh_ltf[-1]["price"] if sh_ltf else price+atr*2
            sl_p = round(max(sh_base*1.0015, price+atr), 8)
            tp1  = round(price-(sl_p-price)*1.5, 8)
            ns   = max((l for l in ssl if l<price*0.999), default=None)
            tp2  = round(ns if ns else price-(sl_p-price)*3.5, 8)

        dist = abs(price-sl_p)
        rr   = round(abs(tp2-price)/dist, 1) if dist>0 else 0
        if rr<2.0: continue

        res = {
            "symbol": symbol, "direction": d, "score": score, "conf": conf,
            "price": round(price,8), "sl": sl_p, "tp1": tp1, "tp2": tp2, "rr": rr,
            "sl_pct":  round(dist/price*100,2),
            "tp1_pct": round(abs(tp1-price)/price*100,2),
            "tp2_pct": round(abs(tp2-price)/price*100,2),
            "session": session,
        }
        if best is None or score>best["score"]: best=res

    return best

# ══════════════════════════════════
#  FORMAT
# ══════════════════════════════════

def format_signal(s, rank):
    sym  = s["symbol"].replace("-","/")
    icon = "📈" if s["direction"]=="LONG" else "📉"
    ri   = "🥇" if rank==1 else ("🥈" if rank==2 else "🥉")
    side = "LONG  🟢" if s["direction"]=="LONG" else "SHORT 🔴"
    conf = min(99, int(s["score"]*0.97))

    return (
        f"{ri} {icon}  NEW SIGNAL  ·  {conf}% Confidence\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"  🪙  {sym}\n"
        f"  📊  {side}\n"
        f"  ⏰  {s['session']}\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"  💰  Entry    {s['price']}\n"
        f"  🛑  SL       {s['sl']}  (-{s['sl_pct']}%)\n"
        f"  🎯  TP1      {s['tp1']}  (+{s['tp1_pct']}%)\n"
        f"  🎯  TP2      {s['tp2']}  (+{s['tp2_pct']}%)\n"
        f"  📐  R : R    1 : {s['rr']}\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
    )

def format_update(pos, cp):
    sym  = pos["symbol"].replace("-","/")
    d    = pos["direction"]
    entry= pos["entry"]
    pnl  = round((cp-entry)/entry*100,2) if d=="LONG" else round((entry-cp)/entry*100,2)
    icon = "📈" if d=="LONG" else "📉"
    pnl_icon = "🟢" if pnl>0 else "🔴"
    hrs  = round(hours_open(pos),1)

    return (
        f"🔄 {icon}  POSITION UPDATE\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"  🪙  {sym}  ·  {d}\n"
        f"  ⏱  Open  {hrs}h\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"  💰  Entry    {entry}\n"
        f"  📍  Now      {cp}\n"
        f"  {pnl_icon}  PnL      {'+' if pnl>0 else ''}{pnl}%\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"  🛑  SL    {pos['sl']}\n"
        f"  🎯  TP1   {pos['tp1']}\n"
        f"  🎯  TP2   {pos['tp2']}"
    )

def format_closed(pos, result, cp):
    sym  = pos["symbol"].replace("-","/")
    d    = pos["direction"]
    entry= pos["entry"]
    pnl  = round((cp-entry)/entry*100,2) if d=="LONG" else round((entry-cp)/entry*100,2)

    if result == "TP2":
        return (
            f"✅  TRADE CLOSED  ·  WIN\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"  🪙  {sym}  ·  {d}\n"
            f"  🎯  TP2 Hit\n"
            f"  💰  Entry  {entry}  →  {cp}\n"
            f"  🟢  PnL    +{abs(pnl)}%\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"  💎  Well done. Risk managed."
        )
    elif result == "TIMEOUT":
        return (
            f"⏰  TRADE CLOSED  ·  TIMEOUT\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"  🪙  {sym}  ·  {d}\n"
            f"  ⏱  Closed after {MAX_POSITION_HOURS}h\n"
            f"  💰  Entry  {entry}  →  {cp}\n"
            f"  {'🟢' if pnl>0 else '🔴'}  PnL    {'+' if pnl>0 else ''}{pnl}%\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
        )
    else:
        return (
            f"❌  TRADE CLOSED  ·  SL HIT\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"  🪙  {sym}  ·  {d}\n"
            f"  🛑  Stop Loss Hit\n"
            f"  💰  Entry  {entry}  →  {cp}\n"
            f"  🔴  PnL    {pnl}%\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"  📌  Risk was managed. Next!"
        )

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
    except: return False

def send_sticker(sid):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendSticker",
            json={"chat_id": TELEGRAM_CHAT_ID, "sticker": sid},
            timeout=10)
    except: pass

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

    # ── چک و گزارش پوزیشن‌های باز ──
    for key in list(state["open"].keys()):
        pos = state["open"].get(key)
        if not pos: continue
        ltf = get_klines(pos["symbol"], LTF, 5)
        if not ltf: continue
        cp = ltf[-1]["c"]

        # چک SL/TP
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

        # گزارش وضعیت پوزیشن باز
        if key in state["open"]:
            entry = pos["entry"]
            d = pos["direction"]
            if d == "LONG":
                pnl = round((cp - entry) / entry * 100, 2)
            else:
                pnl = round((entry - cp) / entry * 100, 2)
            pnl_icon = "🟢" if pnl > 0 else "🔴"
            sym = pos["symbol"].replace("-", "/")
            send_tg(f"📊 POSITION UPDATE\n"
                    f"{'━'*22}\n"
                    f"🪙 {sym} {d}\n"
                    f"💰 Entry:   {entry}\n"
                    f"📍 Current: {cp}\n"
                    f"{'━'*22}\n"
                    f"{pnl_icon} PnL: {'+' if pnl>0 else ''}{pnl}%\n"
                    f"🛑 SL:  {pos['sl']}\n"
                    f"🎯 TP1: {pos['tp1']}\n"
                    f"🎯 TP2: {pos['tp2']}")
        time.sleep(0.5)

    # ── اسکن برای سیگنال جدید ──
    print(f"Scanning {len(SYMBOLS)} symbols...")
    candidates = []

    for symbol in SYMBOLS:
        print(f"  {symbol}...", end=" ", flush=True)
        try:
            sig = analyze(symbol)
            if sig and not is_open(state, symbol, sig["direction"]):
                candidates.append(sig)
                print(f"✓ {sig['direction']} sc:{sig['score']}")
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
        print("No new signals")

if __name__ == "__main__":
    main()
