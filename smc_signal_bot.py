import os
import time
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================= CONFIG =================

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SHEETS_URL = os.environ.get("SHEETS_WEBAPP_URL")
SHEETS_SECRET = os.environ.get("SHEETS_SECRET")
CHART_IMG_KEY = os.environ.get("CHART_IMG_KEY")  # optional - from chart-img.com

BASE = "https://api.toobit.com"

FALLBACK_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "LTCUSDT", "LINKUSDT", "AVAXUSDT",
]

TOP_N = 50
STABLE_SYMBOLS = {"usdt", "usdc", "dai", "tusd", "busd", "usdd", "fdusd", "usdp", "gusd", "eurc", "pyusd"}

TF = "1h"
HTF = "4h"
LTF = "15m"

IRAN_OFFSET = timedelta(hours=3, minutes=30)

session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=0.6,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))


def iran_now():
    return datetime.utcnow() + IRAN_OFFSET


# ================= SYMBOL UNIVERSE (top 50 by market cap, via CoinGecko) =================

def get_top_symbols(n=TOP_N):
    """Top-N coins by market cap (CoinGecko, free/no key) mapped to Toobit-style
    'XXXUSDT' tickers. Stablecoins excluded. NOTE: CoinGecko's ticker symbol
    doesn't always exactly match the exchange's symbol - if a coin fails to
    fetch candles it will just get skipped (see [DATA ERROR] logs)."""
    try:
        r = session.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": n + 20, "page": 1},
            timeout=15
        )
        if r.status_code != 200:
            print(f"[SYMBOL FETCH ERROR] HTTP {r.status_code}")
            return FALLBACK_SYMBOLS

        data = r.json()
        symbols = []
        for coin in data:
            sym = (coin.get("symbol") or "").lower()
            if not sym or sym in STABLE_SYMBOLS:
                continue
            symbols.append(sym.upper() + "USDT")
            if len(symbols) >= n:
                break

        return symbols if symbols else FALLBACK_SYMBOLS

    except Exception as e:
        print("[SYMBOL FETCH ERROR]", e)
        return FALLBACK_SYMBOLS


# ================= CANDLE DATA (Toobit) =================

def candles(symbol, tf=TF, limit=220):
    """Returns closes, highs, lows, volumes (chronological, oldest -> newest)."""
    try:
        r = session.get(
            f"{BASE}/quote/v1/klines",
            params={"symbol": symbol, "interval": tf, "limit": limit},
            timeout=10
        )
        if r.status_code != 200:
            print(f"[DATA ERROR] {symbol} ({tf}): HTTP {r.status_code} - {r.text[:150]}")
            return [], [], [], []

        data = r.json()
        if not data or not isinstance(data, list):
            return [], [], [], []

        # Toobit kline format: [openTime, open, high, low, close, volume, closeTime, ...]
        closes = [float(x[4]) for x in data]
        highs = [float(x[2]) for x in data]
        lows = [float(x[3]) for x in data]
        volumes = [float(x[5]) for x in data]
        return closes, highs, lows, volumes

    except Exception as e:
        print(f"[DATA ERROR] {symbol} ({tf}): {e}")
        return [], [], [], []


# ================= CLASSIC INDICATORS =================

def ema_val(data, period):
    if not data:
        return 0
    if len(data) < period:
        return data[-1]
    k = 2 / (period + 1)
    e = sum(data[:period]) / period
    for v in data[period:]:
        e = v * k + e * (1 - k)
    return e


def ema_list(data, period):
    if len(data) < period:
        return [None] * len(data)
    k = 2 / (period + 1)
    result = [None] * (period - 1)
    e = sum(data[:period]) / period
    result.append(e)
    for v in data[period:]:
        e = v * k + e * (1 - k)
        result.append(e)
    return result


def rsi_list(data, period=14):
    if len(data) < period + 1:
        return [None] * len(data)
    gains = [0.0] * len(data)
    losses = [0.0] * len(data)
    for i in range(1, len(data)):
        diff = data[i] - data[i - 1]
        gains[i] = max(diff, 0)
        losses[i] = max(-diff, 0)

    rsis = [None] * len(data)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period

    def to_rsi(ag, al):
        if al == 0:
            return 100.0
        rs = ag / al
        return 100 - (100 / (1 + rs))

    rsis[period] = to_rsi(avg_gain, avg_loss)
    for i in range(period + 1, len(data)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsis[i] = to_rsi(avg_gain, avg_loss)
    return rsis


def macd_values(data, fast=12, slow=26, signal_p=9):
    ema_fast = ema_list(data, fast)
    ema_slow = ema_list(data, slow)
    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        macd_line.append(None if (f is None or s is None) else f - s)

    valid = [v for v in macd_line if v is not None]
    if len(valid) < signal_p + 1:
        return 0, 0, 0, 0, 0

    signal_series = ema_list(valid, signal_p)
    macd_now = valid[-1]
    macd_prev = valid[-2]
    signal_now = signal_series[-1] if signal_series[-1] is not None else macd_now
    signal_prev = signal_series[-2] if len(signal_series) >= 2 and signal_series[-2] is not None else signal_now
    return macd_now, signal_now, macd_now - signal_now, macd_prev, macd_prev - signal_prev


def stoch_rsi_val(data, rsi_period=14, stoch_period=14):
    rsis = rsi_list(data, rsi_period)
    valid = [v for v in rsis if v is not None]
    if len(valid) < stoch_period:
        return 50.0
    window = valid[-stoch_period:]
    lo, hi = min(window), max(window)
    if hi == lo:
        return 50.0
    return (valid[-1] - lo) / (hi - lo) * 100


def obv_trend(closes, volumes, lookback=10):
    if len(closes) < lookback + 1:
        return 0
    obv = 0.0
    series = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i]
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i]
        series.append(obv)
    recent = series[-lookback:]
    return recent[-1] - recent[0]


def atr_val(highs, lows, closes, period=14):
    if len(closes) < 2:
        return 0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    return sum(trs[-period:]) / period


def _wilder_smooth(values, period):
    if len(values) < period + 1:
        return [0.0] * len(values)
    result = [None] * period
    total = sum(values[1:period + 1])
    result.append(total)
    prev = total
    for v in values[period + 1:]:
        prev = prev - (prev / period) + v
        result.append(prev)
    return result


def adx_val(highs, lows, closes, period=14):
    if len(closes) < period * 2:
        return 0
    plus_dm, minus_dm, trs = [0.0], [0.0], [0.0]
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    tr_s = _wilder_smooth(trs, period)
    plus_s = _wilder_smooth(plus_dm, period)
    minus_s = _wilder_smooth(minus_dm, period)

    dx_values = []
    for t, p, m in zip(tr_s, plus_s, minus_s):
        if not t:
            continue
        pdi, mdi = 100 * p / t, 100 * m / t
        denom = pdi + mdi
        dx_values.append(0 if denom == 0 else 100 * abs(pdi - mdi) / denom)

    if not dx_values:
        return 0
    if len(dx_values) < period:
        return dx_values[-1]
    return sum(dx_values[-period:]) / period


# ================= RSI DIVERGENCE =================

def rsi_divergence(closes, rsis, direction, lookback=30):
    """Simplified divergence check: compares the price extreme + RSI value in
    the first half vs second half of the lookback window."""
    n = len(closes)
    start = max(2, n - lookback)
    sub_c = closes[start:]
    sub_r = rsis[start:]
    half = len(sub_c) // 2
    if half < 3:
        return False

    if direction == "LONG":
        low1 = min(sub_c[:half])
        low2 = min(sub_c[half:])
        i1 = sub_c[:half].index(low1)
        i2 = half + sub_c[half:].index(low2)
        r1, r2 = sub_r[i1], sub_r[i2]
        if r1 is None or r2 is None:
            return False
        return low2 < low1 and r2 > r1  # bullish divergence
    else:
        high1 = max(sub_c[:half])
        high2 = max(sub_c[half:])
        i1 = sub_c[:half].index(high1)
        i2 = half + sub_c[half:].index(high2)
        r1, r2 = sub_r[i1], sub_r[i2]
        if r1 is None or r2 is None:
            return False
        return high2 > high1 and r2 < r1  # bearish divergence


# ================= ICT: STRUCTURE (BOS / CHOCH) + FVG =================

def find_swings(highs, lows, arm=2):
    swing_highs, swing_lows = [], []
    for i in range(arm, len(highs) - arm):
        if highs[i] == max(highs[i - arm:i + arm + 1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i - arm:i + arm + 1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def detect_structure(highs, lows, closes):
    """Returns 'BOS_UP', 'BOS_DOWN', 'CHOCH_UP', 'CHOCH_DOWN', or None."""
    swing_highs, swing_lows = find_swings(highs, lows)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    last_price = closes[-1]
    last_sh, prev_sh = swing_highs[-1][1], swing_highs[-2][1]
    last_sl, prev_sl = swing_lows[-1][1], swing_lows[-2][1]

    if last_price > last_sh and last_sh > prev_sh:
        return "BOS_UP"
    if last_price < last_sl and last_sl < prev_sl:
        return "BOS_DOWN"
    if last_price > last_sh and last_sh <= prev_sh:
        return "CHOCH_UP"
    if last_price < last_sl and last_sl >= prev_sl:
        return "CHOCH_DOWN"
    return None


def detect_fvg_zones(highs, lows, closes, lookback=40):
    """Classic 3-candle Fair Value Gap detection."""
    zones = []
    n = len(closes)
    start = max(2, n - lookback)
    for i in range(start, n):
        if lows[i] > highs[i - 2]:
            zones.append((highs[i - 2], lows[i], "bullish"))
        if highs[i] < lows[i - 2]:
            zones.append((highs[i], lows[i - 2], "bearish"))
    return zones


def price_in_fvg(price, zones, direction):
    want = "bullish" if direction == "LONG" else "bearish"
    return any(typ == want and lo <= price <= hi for lo, hi, typ in zones)


def near_session_liquidity(price, highs, lows, lookback=8, tolerance=0.003):
    """Proxy for session high/low liquidity zones using the recent candle range."""
    if len(highs) < lookback:
        return False
    session_high = max(highs[-lookback:])
    session_low = min(lows[-lookback:])
    return (abs(price - session_high) / price <= tolerance) or (abs(price - session_low) / price <= tolerance)


# ================= VOLUME PROFILE (POC) =================

def volume_poc(closes, volumes, bins=20):
    if not closes:
        return None
    lo, hi = min(closes), max(closes)
    if hi == lo:
        return closes[-1]
    bin_size = (hi - lo) / bins
    vol_by_bin = [0.0] * bins
    for c, v in zip(closes, volumes):
        idx = min(int((c - lo) / bin_size), bins - 1)
        vol_by_bin[idx] += v
    max_idx = vol_by_bin.index(max(vol_by_bin))
    return lo + (max_idx + 0.5) * bin_size


# ================= FUNDING RATE (best-effort; endpoint unverified) =================

def funding_rate(symbol):
    """NOTE: exact Toobit funding-rate endpoint/response shape isn't verified
    in this environment. If this 404s or the fields don't match, check the
    [FUNDING ERROR] log line and send it over - easy to patch."""
    try:
        r = session.get(f"{BASE}/quote/v1/funding/rate", params={"symbol": symbol}, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        rate = data.get("rate") or data.get("fundingRate")
        if rate is None and isinstance(data.get("data"), dict):
            rate = data["data"].get("rate")
        return float(rate) if rate is not None else None
    except Exception as e:
        print(f"[FUNDING ERROR] {symbol}: {e}")
        return None


def funding_agree(symbol, direction):
    rate = funding_rate(symbol)
    if rate is None:
        return False
    if direction == "SHORT" and rate > 0.0005:
        return True
    if direction == "LONG" and rate < -0.0005:
        return True
    return False


# ================= FEAR & GREED INDEX =================

def fear_greed():
    try:
        r = session.get("https://api.alternative.me/fng/", timeout=8)
        if r.status_code != 200:
            return None
        return int(r.json()["data"][0]["value"])
    except Exception as e:
        print("[FNG ERROR]", e)
        return None


def fear_greed_ok(direction, fng):
    if fng is None:
        return True  # don't block on failure
    if direction == "LONG" and fng >= 85:
        return False
    if direction == "SHORT" and fng <= 15:
        return False
    return True


# ================= LOWER TIMEFRAME CONFLICT =================

def lower_tf_conflict(symbol, direction):
    closes, highs, lows, _ = candles(symbol, tf=LTF, limit=30)
    if len(closes) < 12:
        return False
    atr15 = atr_val(highs, lows, closes, period=10)
    if atr15 <= 0:
        return False
    last_range = highs[-1] - lows[-1]
    body_move = closes[-1] - closes[-2]
    sharp = last_range > 1.5 * atr15
    if direction == "LONG" and sharp and body_move < 0:
        return True
    if direction == "SHORT" and sharp and body_move > 0:
        return True
    return False


def htf_trend(symbol):
    closes, _, _, _ = candles(symbol, tf=HTF, limit=220)
    if len(closes) < 60:
        return None
    e50 = ema_val(closes, 50)
    e200 = ema_val(closes, min(200, len(closes) - 1))
    return "LONG" if e50 > e200 else "SHORT"


# ================= SCORING: 5-STAGE CONFIRMATION =================

def score_symbol(symbol):
    try:
        closes, highs, lows, volumes = candles(symbol)
        if len(closes) < 60:
            return {"symbol": symbol, "signal": False, "reason": "insufficient_data"}

        price = closes[-1]

        # base direction candidate from 1h trend
        e50 = ema_val(closes, 50)
        e200 = ema_val(closes, min(200, len(closes) - 1))
        base_dir = "LONG" if e50 > e200 else "SHORT"

        # --- GATE 1 (mandatory): market structure - BOS or CHOCH ---
        structure = detect_structure(highs, lows, closes)
        want_structure = {"LONG": ("BOS_UP", "CHOCH_UP"), "SHORT": ("BOS_DOWN", "CHOCH_DOWN")}[base_dir]
        if structure not in want_structure:
            return {"symbol": symbol, "signal": False, "reason": "no_structure_break"}

        direction = base_dir

        # --- GATE 2 (mandatory): entry zone - FVG or session liquidity ---
        fvg_zones = detect_fvg_zones(highs, lows, closes)
        in_zone = price_in_fvg(price, fvg_zones, direction) or near_session_liquidity(price, highs, lows)
        if not in_zone:
            return {"symbol": symbol, "signal": False, "reason": "no_entry_zone"}

        # --- GATE 3 (need >=2 of 3): momentum confirmation ---
        rsis = rsi_list(closes)
        div_agree = rsi_divergence(closes, rsis, direction)

        macd_now, signal_now, hist_now, macd_prev, hist_prev = macd_values(closes)
        macd_agree = (macd_now > signal_now) if direction == "LONG" else (macd_now < signal_now)

        srsi = stoch_rsi_val(closes)
        stoch_agree = (srsi < 20) if direction == "LONG" else (srsi > 80)

        momentum_votes = sum([div_agree, macd_agree, stoch_agree])
        if momentum_votes < 2:
            return {"symbol": symbol, "signal": False, "reason": "weak_momentum", "votes": momentum_votes}

        # --- GATE 4 (mandatory, any one): volume / money-flow confirmation ---
        obv_diff = obv_trend(closes, volumes)
        obv_agree = (obv_diff > 0) if direction == "LONG" else (obv_diff < 0)

        poc = volume_poc(closes, volumes)
        poc_agree = False
        if poc:
            poc_agree = (price >= poc) if direction == "LONG" else (price <= poc)

        fund_agree = funding_agree(symbol, direction)

        if not (obv_agree or poc_agree or fund_agree):
            return {"symbol": symbol, "signal": False, "reason": "no_volume_confirmation"}

        # --- GATE 5 (mandatory): final filters ---
        adx = adx_val(highs, lows, closes)
        if adx and adx < 18:
            return {"symbol": symbol, "signal": False, "reason": "low_adx", "adx": round(adx, 1)}

        higher_trend = htf_trend(symbol)
        if higher_trend is not None and higher_trend != direction:
            return {"symbol": symbol, "signal": False, "reason": "htf_disagree"}

        if lower_tf_conflict(symbol, direction):
            return {"symbol": symbol, "signal": False, "reason": "ltf_conflict"}

        fng = fear_greed()
        if not fear_greed_ok(direction, fng):
            return {"symbol": symbol, "signal": False, "reason": "fear_greed_extreme"}

        # ATR-based SL/TP
        atr = atr_val(highs, lows, closes)
        if atr <= 0:
            atr = price * 0.01

        if direction == "LONG":
            sl = price - 1.5 * atr
            tp1 = price + 2.0 * atr
            tp2 = price + 3.5 * atr
        else:
            sl = price + 1.5 * atr
            tp1 = price - 2.0 * atr
            tp2 = price - 3.5 * atr

        risk = abs(price - sl)
        reward = abs(tp2 - price)
        rr = round(reward / risk, 2) if risk > 0 else 0

        if rr < 1.5:
            return {"symbol": symbol, "signal": False, "reason": "poor_rr", "rr": rr}

        # confidence score: base on how many gates were exceeded (informational)
        score = 60 + momentum_votes * 8 + (10 if structure.startswith("BOS") else 5) + min(adx, 30) * 0.3
        score = min(round(score), 99)
        probability = min(88, round(40 + score * 0.5 + min(adx, 40) * 0.2))

        return {
            "symbol": symbol,
            "signal": True,
            "dir": direction,
            "structure": structure,
            "score": score,
            "price": round(price, 6),
            "sl": round(sl, 6),
            "tp1": round(tp1, 6),
            "tp2": round(tp2, 6),
            "rr": rr,
            "adx": round(adx, 1),
            "probability": probability,
        }

    except Exception as e:
        print(f"[SCORE ERROR] {symbol}: {e}")
        return {"symbol": symbol, "signal": False, "reason": "error", "detail": str(e)}


# ================= GOOGLE SHEETS =================

def sheets_call(method, params=None, json_body=None):
    if not SHEETS_URL or not SHEETS_SECRET:
        return None
    try:
        if method == "GET":
            q = {"secret": SHEETS_SECRET}
            if params:
                q.update(params)
            r = session.get(SHEETS_URL, params=q, timeout=15)
        else:
            body = {"secret": SHEETS_SECRET}
            if json_body:
                body.update(json_body)
            r = session.post(SHEETS_URL, json=body, timeout=15)

        if r.status_code != 200:
            print(f"[SHEETS ERROR] HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.json()
    except Exception as e:
        print("[SHEETS ERROR]", e)
        return None


def sheet_log_signal(s):
    sheets_call("POST", json_body={
        "action": "append",
        "data": {
            "symbol": s["symbol"],
            "dir": s["dir"],
            "entry": s["price"],
            "sl": s["sl"],
            "tp1": s["tp1"],
            "tp2": s["tp2"],
            "timestamp": iran_now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    })


def sheet_list_open():
    result = sheets_call("GET", params={"action": "list_open"})
    return result.get("rows", []) if result else []


def sheet_update_status(row_id, status, closed_price):
    sheets_call("POST", json_body={
        "action": "update_status",
        "data": {
            "id": row_id,
            "status": status,
            "closed_price": closed_price,
            "closed_time": iran_now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    })


def sheet_weekly_stats():
    return sheets_call("GET", params={"action": "weekly_stats"})


def sheet_get_meta(key):
    result = sheets_call("GET", params={"action": "get_meta", "key": key})
    return result.get("value") if result else None


def sheet_set_meta(key, value):
    sheets_call("POST", json_body={"action": "set_meta", "data": {"key": key, "value": value}})


def check_open_signals():
    """Checks every OPEN signal's current price and % progress toward TP/SL.
    Updates status in the sheet if TP/SL was hit. Returns status lines."""
    open_rows = sheet_list_open()
    lines = []

    for row in open_rows:
        symbol = row.get("symbol")
        direction = row.get("dir")
        entry = float(row.get("entry", 0))
        sl = float(row.get("sl", 0))
        tp1 = float(row.get("tp1", 0))
        tp2 = float(row.get("tp2", 0))

        closes, _, _, _ = candles(symbol, tf="15m", limit=2)
        if not closes:
            continue
        price = closes[-1]

        status = None
        if direction == "LONG":
            if price >= tp2:
                status = "TP2 HIT ✅"
            elif price >= tp1:
                status = "TP1 HIT ✅"
            elif price <= sl:
                status = "SL HIT ❌"
            else:
                progress = round((price - entry) / (tp2 - entry) * 100, 1) if tp2 != entry else 0
        else:
            if price <= tp2:
                status = "TP2 HIT ✅"
            elif price <= tp1:
                status = "TP1 HIT ✅"
            elif price >= sl:
                status = "SL HIT ❌"
            else:
                progress = round((entry - price) / (entry - tp2) * 100, 1) if entry != tp2 else 0

        if status:
            sheet_update_status(row.get("id"), status, price)
            lines.append(f"{symbol} ({direction}): {status} @ {price}")
        else:
            lines.append(f"{symbol} ({direction}): {progress}% تا TP، قیمت الان {price}")

    return lines


# ================= WEEKLY REPORT (Iran time, Thursday evening) =================

def is_weekly_report_window():
    t = iran_now()
    return t.weekday() == 3 and 20 <= t.hour < 22  # Mon=0 -> Thursday=3


def send_weekly_report_if_due():
    if not is_weekly_report_window():
        return
    week_marker = iran_now().strftime("%Y-W%U")
    if sheet_get_meta("last_weekly_report") == week_marker:
        return

    stats = sheet_weekly_stats()
    if stats:
        send(
            f"📅 گزارش هفتگی\n"
            f"تعداد کل سیگنال: {stats.get('total', 0)}\n"
            f"✅ TP خورده: {stats.get('tp_hits', 0)}\n"
            f"❌ SL خورده: {stats.get('sl_hits', 0)}\n"
            f"🕒 هنوز باز: {stats.get('open', 0)}"
        )
        sheet_set_meta("last_weekly_report", week_marker)


# ================= TELEGRAM =================

def send(msg):
    if not TOKEN or not CHAT_ID:
        print("[WARNING] TELEGRAM TOKEN OR CHAT ID MISSING")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("[TELEGRAM ERROR]", e)


def send_photo(image_bytes, caption):
    if not TOKEN or not CHAT_ID or not image_bytes:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"photo": ("chart.png", image_bytes)},
            timeout=20
        )
        return r.status_code == 200
    except Exception as e:
        print("[TELEGRAM PHOTO ERROR]", e)
        return False


def get_chart_image(symbol):
    """Best-effort chart-img.com snapshot. Needs CHART_IMG_KEY secret set.
    NOTE: exact params/exchange-prefix aren't verified here - check
    [CHART IMG ERROR] logs if it never sends photos and adjust as needed.
    If the free quota is exhausted (402/429), this returns None and the bot
    just falls back to text-only signals automatically."""
    if not CHART_IMG_KEY:
        return None
    try:
        r = session.get(
            "https://api.chart-img.com/v1/tradingview/advanced-chart",
            params={"symbol": f"BINANCE:{symbol}", "interval": "1h", "key": CHART_IMG_KEY},
            timeout=15
        )
        if r.status_code == 200:
            return r.content
        if r.status_code in (402, 429):
            print("[CHART IMG] free quota likely exhausted - sending text-only from now on")
        else:
            print(f"[CHART IMG ERROR] HTTP {r.status_code}")
        return None
    except Exception as e:
        print("[CHART IMG ERROR]", e)
        return None


def fmt(s):
    direction_emoji = "📈" if s["dir"] == "LONG" else "📉"
    side_word = "LONG" if s["dir"] == "LONG" else "SELL"
    side_mark = "🟢🟢" if s["dir"] == "LONG" else "🔴🔴"

    entry, sl, tp1, tp2 = s["price"], s["sl"], s["tp1"], s["tp2"]

    if s["dir"] == "LONG":
        sl_pct = round((entry - sl) / entry * 100, 2)
        tp1_pct = round((tp1 - entry) / entry * 100, 2)
        tp2_pct = round((tp2 - entry) / entry * 100, 2)
    else:
        sl_pct = round((sl - entry) / entry * 100, 2)
        tp1_pct = round((entry - tp1) / entry * 100, 2)
        tp2_pct = round((entry - tp2) / entry * 100, 2)

    tehran_str = iran_now().strftime("%Y-%m-%d %H:%M")

    return f"""🥇

{side_mark} {side_word} {direction_emoji}
Symbol: {s['symbol']}
Structure: {s['structure']}

🏆 Confidence: {s['score']}%
📊 ADX: {s['adx']}
🎲 Est. TP Probability: {s['probability']}%
💰 Entry: {entry}
🛑 SL: {sl}  (-{sl_pct}%)
🎯 TP1: {tp1}  (+{tp1_pct}%)
🎯 TP2: {tp2}  (+{tp2_pct}%)
📐 R:R  1:{s['rr']}
🕒 {tehran_str} (تهران)

━━━━━━━━━━━━━━━━━━━━━
"""


# ================= SCAN =================

def run_scan():
    symbols = get_top_symbols(TOP_N)
    print(f"Scanning {len(symbols)} symbols...")

    results = []
    reason_counts = {}

    with ThreadPoolExecutor(max_workers=6) as executor:
        outputs = list(executor.map(score_symbol, symbols))

    for result in outputs:
        if not result:
            reason_counts["no_result"] = reason_counts.get("no_result", 0) + 1
            continue
        if result.get("signal"):
            results.append(result)
        else:
            reason = result.get("reason", "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    print("---- SCAN BREAKDOWN ----")
    print(f"Passed all filters: {len(results)}")
    for reason, count in reason_counts.items():
        print(f"Rejected [{reason}]: {count}")
    print("------------------------")

    results.sort(key=lambda x: x["score"], reverse=True)
    top_signals = results[:2]

    if top_signals:
        for signal in top_signals:
            caption = fmt(signal)
            image = get_chart_image(signal["symbol"])
            sent_photo = send_photo(image, caption) if image else False
            if not sent_photo:
                send(caption)
            sheet_log_signal(signal)
    else:
        breakdown = ", ".join(f"{r}: {c}" for r, c in reason_counts.items())
        send(f"⚪ NO STRONG SIGNAL\nScanned: {len(symbols)}\nBreakdown -> {breakdown}\n{iran_now()}")

    send(f"SCAN DONE {iran_now()}")


# ================= MAIN LOOP =================

def main():
    print("ADVANCED ICT SIGNAL BOT STARTED")
    tick = 0

    while True:
        try:
            # every hour: report status of open signals
            lines = check_open_signals()
            if lines:
                send("📋 آپدیت ساعتی سیگنال‌های باز:\n" + "\n".join(lines))

            # every 2 hours: full scan for new signals
            if tick % 2 == 0:
                run_scan()

            send_weekly_report_if_due()

        except Exception as e:
            print("[BOT ERROR]", e)

        tick += 1
        time.sleep(3600)  # 1 hour


if __name__ == "__main__":
    main()

