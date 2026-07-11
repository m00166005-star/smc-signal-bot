import os
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BASE = "https://api.kucoin.com"

# fallback list, used only if the dynamic top-50 fetch fails
FALLBACK_SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "XRP-USDT",
    "DOGE-USDT", "ADA-USDT", "TRX-USDT", "AVAX-USDT", "LINK-USDT",
    "DOT-USDT", "MATIC-USDT", "LTC-USDT", "BCH-USDT", "ATOM-USDT",
    "NEAR-USDT", "APT-USDT", "ETC-USDT", "UNI-USDT", "FIL-USDT"
]

TOP_N = 50
STABLE_BASES = {"USDC", "DAI", "TUSD", "BUSD", "USDD", "FDUSD", "USDP", "GUSD", "EURC", "PYUSD"}
LEVERAGED_TAGS = ("3L", "3S", "5L", "5S", "2L", "2S")

TF = "1hour"
HTF = "4hour"

# resilient HTTP session: automatic retry on timeouts / rate limits / 5xx
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=0.6,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))


# ================= DATA =================

def candles(symbol, tf=TF, limit=220):
    """Fetch OHLCV candles from KuCoin. Returns closes, highs, lows, volumes
    (chronological order, oldest -> newest)."""
    try:
        r = session.get(
            f"{BASE}/api/v1/market/candles",
            params={"symbol": symbol, "type": tf},
            timeout=10
        )

        if r.status_code != 200:
            return [], [], [], []

        data = r.json().get("data", [])

        if not data:
            return [], [], [], []

        # KuCoin format: [time, open, close, high, low, volume, turnover]
        chunk = list(reversed(data[:limit]))

        closes = [float(x[2]) for x in chunk]
        highs = [float(x[3]) for x in chunk]
        lows = [float(x[4]) for x in chunk]
        volumes = [float(x[5]) for x in chunk]

        return closes, highs, lows, volumes

    except Exception as e:
        print(f"[DATA ERROR] {symbol} ({tf}): {e}")
        return [], [], [], []


# ================= SYMBOL UNIVERSE =================

def get_top_symbols(n=TOP_N, quote="USDT"):
    """Fetch the top-N most-traded USDT pairs on KuCoin by 24h turnover.
    Falls back to a static list if the API call fails."""
    try:
        r = session.get(f"{BASE}/api/v1/market/allTickers", timeout=10)
        if r.status_code != 200:
            return FALLBACK_SYMBOLS

        tickers = r.json().get("data", {}).get("ticker", [])
        candidates = []

        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith(f"-{quote}"):
                continue

            base = sym.split("-")[0]

            if base in STABLE_BASES:
                continue
            if any(tag in base for tag in LEVERAGED_TAGS):
                continue

            try:
                vol_value = float(t.get("volValue") or 0)
            except (TypeError, ValueError):
                vol_value = 0

            candidates.append((sym, vol_value))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top = [sym for sym, _ in candidates[:n]]

        return top if top else FALLBACK_SYMBOLS

    except Exception as e:
        print("[SYMBOL FETCH ERROR]", e)
        return FALLBACK_SYMBOLS


# ================= INDICATORS =================

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

    hist_now = macd_now - signal_now
    hist_prev = macd_prev - signal_prev

    return macd_now, signal_now, hist_now, macd_prev, hist_prev


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


def bollinger(data, period=20, mult=2):
    if len(data) < period:
        price = data[-1] if data else 0
        return price, price, price

    window = data[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std = variance ** 0.5

    return mean + mult * std, mean, mean - mult * std


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
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
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
    """Approximate Wilder ADX - measures trend strength (0-100).
    Used only as a trend/no-trend gate, not for precision trading."""
    if len(closes) < period * 2:
        return 0

    plus_dm = [0.0]
    minus_dm = [0.0]
    trs = [0.0]

    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        trs.append(tr)

    tr_s = _wilder_smooth(trs, period)
    plus_s = _wilder_smooth(plus_dm, period)
    minus_s = _wilder_smooth(minus_dm, period)

    dx_values = []
    for t, p, m in zip(tr_s, plus_s, minus_s):
        if not t:
            continue
        pdi = 100 * p / t
        mdi = 100 * m / t
        denom = pdi + mdi
        dx_values.append(0 if denom == 0 else 100 * abs(pdi - mdi) / denom)

    if not dx_values:
        return 0

    if len(dx_values) < period:
        return dx_values[-1]

    return sum(dx_values[-period:]) / period


# ================= HIGHER TIMEFRAME TREND =================

def htf_trend(symbol):
    """Returns 'LONG', 'SHORT', or None (unknown / not enough data)."""
    closes, _, _, _ = candles(symbol, tf=HTF, limit=220)

    if len(closes) < 60:
        return None

    e50 = ema_val(closes, 50)
    e200 = ema_val(closes, min(200, len(closes) - 1))

    return "LONG" if e50 > e200 else "SHORT"


# ================= SCORING =================

def score_symbol(symbol):

    try:
        closes, highs, lows, volumes = candles(symbol)

        if len(closes) < 60:
            return {"symbol": symbol, "signal": False, "reason": "insufficient_data"}

        price = closes[-1]

        # --- gate 1: trend strength (skip choppy/ranging markets) ---
        adx = adx_val(highs, lows, closes)
        if adx and adx < 18:
            return {"symbol": symbol, "signal": False, "reason": "low_adx", "adx": round(adx, 1)}

        long_score = 0
        short_score = 0

        # 1) Trend filter - EMA50 vs EMA200 (weight 20)
        e50 = ema_val(closes, 50)
        e200 = ema_val(closes, min(200, len(closes) - 1))
        if e50 > e200:
            long_score += 20
        else:
            short_score += 20

        # 2) MACD crossover + histogram momentum (weight 20)
        macd_now, signal_now, hist_now, macd_prev, hist_prev = macd_values(closes)
        if macd_now > signal_now:
            long_score += 12
        else:
            short_score += 12
        if hist_now > hist_prev:
            long_score += 8
        else:
            short_score += 8

        # 3) RSI zone (weight 15)
        rsi_series = rsi_list(closes)
        rsi_now = rsi_series[-1] if rsi_series[-1] is not None else 50
        if rsi_now < 35:
            long_score += 15
        elif rsi_now > 65:
            short_score += 15
        elif rsi_now < 50:
            short_score += 5
        else:
            long_score += 5

        # 4) Stochastic RSI momentum (weight 15)
        srsi = stoch_rsi_val(closes)
        if srsi < 20:
            long_score += 15
        elif srsi > 80:
            short_score += 15

        # 5) Bollinger Bands position (weight 15)
        upper, mid, lower = bollinger(closes)
        if price <= lower:
            long_score += 15
        elif price >= upper:
            short_score += 15
        elif price < mid:
            short_score += 5
        else:
            long_score += 5

        # 6) OBV volume trend confirmation (weight 15)
        obv_diff = obv_trend(closes, volumes)
        if obv_diff > 0:
            long_score += 15
        elif obv_diff < 0:
            short_score += 15

        if long_score < 65 and short_score < 65:
            return {
                "symbol": symbol, "signal": False, "reason": "weak_confluence",
                "long_score": long_score, "short_score": short_score
            }

        direction = "LONG" if long_score >= short_score else "SHORT"
        score = max(long_score, short_score)

        # --- gate 2: higher timeframe (4h) trend must agree ---
        higher_trend = htf_trend(symbol)
        if higher_trend is not None and higher_trend != direction:
            return {
                "symbol": symbol, "signal": False, "reason": "htf_disagree",
                "score": score, "wanted": direction, "htf": higher_trend
            }

        # ATR-based dynamic SL/TP
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

        # exact risk:reward from real distances (not approximated)
        risk = abs(price - sl)
        reward = abs(tp2 - price)
        rr = round(reward / risk, 2) if risk > 0 else 0

        # gate 3: don't send signals with a poor risk:reward
        if rr < 1.5:
            return {
                "symbol": symbol, "signal": False, "reason": "poor_rr",
                "score": score, "rr": rr
            }

        # Heuristic confidence estimate that TP gets hit.
        # NOTE: this is NOT a backtested statistical probability - it's a
        # weighted estimate from signal strength (score) + trend strength (ADX).
        # A real probability would require historical backtesting of this exact logic.
        probability = min(88, round(40 + score * 0.5 + min(adx, 40) * 0.2))

        return {
            "symbol": symbol,
            "signal": True,
            "dir": direction,
            "score": min(score, 99),
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


# ================= TELEGRAM =================

def send(msg):

    if not TOKEN or not CHAT_ID:
        print("[WARNING] TELEGRAM TOKEN OR CHAT ID MISSING")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": msg
            },
            timeout=10
        )

    except Exception as e:
        print("[TELEGRAM ERROR]", e)


def get_session(hour_utc):
    if 0 <= hour_utc < 8:
        return "🗼 Asia (Tokyo/Sydney)"
    elif 8 <= hour_utc < 13:
        return "🎡 London"
    elif 13 <= hour_utc < 17:
        return "🌉 London-NY Overlap"
    else:
        return "🗽 New York"


def fmt(s, rank):

    direction_emoji = "📈" if s["dir"] == "LONG" else "📉"
    side_word = "LONG" if s["dir"] == "LONG" else "SELL"
    side_mark = "🟢🟢" if s["dir"] == "LONG" else "🔴🔴"

    confidence = s["score"]
    entry = s["price"]
    sl = s["sl"]
    tp1 = s["tp1"]
    tp2 = s["tp2"]

    if s["dir"] == "LONG":
        sl_pct = round(((entry - sl) / entry) * 100, 2)
        tp1_pct = round(((tp1 - entry) / entry) * 100, 2)
        tp2_pct = round(((tp2 - entry) / entry) * 100, 2)
    else:
        sl_pct = round(((sl - entry) / entry) * 100, 2)
        tp1_pct = round(((entry - tp1) / entry) * 100, 2)
        tp2_pct = round(((entry - tp2) / entry) * 100, 2)

    now = datetime.now()
    trading_session = get_session(now.hour)

    return f"""

🦁 PRO SIGNAL

{side_mark} {side_word} {direction_emoji}
Symbol: {s['symbol']}

🏆 Confidence: {confidence}%
📊 ADX: {s['adx']}
🎲 Est. TP Probability: {s['probability']}%
💰 Entry: {entry}
🛑 SL: {sl}  (-{sl_pct}%)
🎯 TP1: {tp1}  (+{tp1_pct}%)
🎯 TP2: {tp2}  (+{tp2_pct}%)
📐 R:R  1:{s['rr']}
{trading_session}

━━━━━━━━━━━━━━━━━━━━━

"""


# ================= SCAN =================

def run_scan():

    symbols = get_top_symbols(TOP_N)
    print(f"Scanning {len(symbols)} symbols...")

    results = []
    reason_counts = {}

    with ThreadPoolExecutor(max_workers=8) as executor:
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

    # transparent per-scan breakdown, visible in the GitHub Actions log
    print("---- SCAN BREAKDOWN ----")
    print(f"Passed all filters (signals found): {len(results)}")
    for reason, count in reason_counts.items():
        print(f"Rejected [{reason}]: {count}")
    print("------------------------")

    results.sort(key=lambda x: x["score"], reverse=True)

    top_signals = results[:2]

    if top_signals:
        for rank, signal in enumerate(top_signals, start=1):
            send(fmt(signal, rank))
    else:
        breakdown = ", ".join(f"{r}: {c}" for r, c in reason_counts.items())
        send(
            f"⚪ NO STRONG SIGNAL\n"
            f"Scanned: {len(symbols)} coins\n"
            f"Breakdown -> {breakdown}\n"
            f"{datetime.now()}"
        )

    send(f"SCAN DONE {datetime.now()}")


# ================= MAIN =================

def main():

    print("HIGH-ACCURACY SIGNAL BOT STARTED")

    while True:
        try:
            run_scan()
        except Exception as e:
            print("[BOT ERROR]", e)

        time.sleep(1800)


# ================= START =================

if __name__ == "__main__":
    main()

