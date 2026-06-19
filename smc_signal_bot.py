import os
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BASE = "https://api.kucoin.com"

SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "XRP-USDT",
    "DOGE-USDT", "ADA-USDT", "TRX-USDT", "AVAX-USDT", "LINK-USDT",
    "DOT-USDT", "MATIC-USDT", "LTC-USDT", "BCH-USDT", "ATOM-USDT",
    "NEAR-USDT", "APT-USDT", "ETC-USDT", "UNI-USDT", "FIL-USDT"
]

TF = "1hour"
session = requests.Session()


# ================= DATA =================

def candles(symbol):
    try:
        r = session.get(
            f"{BASE}/api/v1/market/candles",
            params={"symbol": symbol, "type": TF},
            timeout=10
        )

        if r.status_code != 200:
            return []

        data = r.json().get("data", [])

        if not data:
            return []

        return [float(x[2]) for x in reversed(data[:100])]

    except Exception as e:
        print(f"[DATA ERROR] {symbol}: {e}")
        return []


# ================= INDICATORS =================

def ema(data, p):
    if len(data) < p:
        return data[-1] if data else 0

    k = 2 / (p + 1)
    e = sum(data[:p]) / p

    for v in data[p:]:
        e = v * k + e * (1 - k)

    return e


def rsi(data):
    if len(data) < 20:
        return 50

    gain = 0
    loss = 0

    for i in range(-14, -1):
        diff = data[i] - data[i - 1]

        if diff > 0:
            gain += diff
        else:
            loss -= diff

    if loss == 0:
        return 100

    rs = gain / loss
    return 100 - (100 / (1 + rs))


def volatility(data):
    if len(data) < 15:
        return 0

    return max(data[-15:]) - min(data[-15:])


# ================= SCORING =================

def score_symbol(symbol):

    prices = candles(symbol)

    if len(prices) < 20:
        return None

    price = prices[-1]

    e50 = ema(prices, 50)
    e200 = ema(prices, 200)

    r = rsi(prices)
    vol = volatility(prices)

    long_score = 0
    short_score = 0

    if e50 > e200:
        long_score += 40
    else:
        short_score += 40

    if r < 40:
        long_score += 25
    elif r > 60:
        short_score += 25

    if vol > price * 0.012:
        long_score += 15
        short_score += 15

    if prices[-1] > prices[-2]:
        long_score += 10
    else:
        short_score += 10

    if long_score < 55 and short_score < 55:
        return None

    direction = "LONG" if long_score >= short_score else "SHORT"
    score = max(long_score, short_score)

    return {
        "symbol": symbol,
        "dir": direction,
        "score": score,
        "price": round(price, 6),
        "sl": round(
            price * (0.98 if direction == "LONG" else 1.02),
            6
        ),
        "tp": round(
            price * (1.03 if direction == "LONG" else 0.97),
            6
        )
    }


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


def fmt(s, rank):

    medal = {
        1: "🥇",
        2: "🥈",
        3: "🥉"
    }.get(rank, "🏅")

    direction_emoji = "📈" if s["dir"] == "LONG" else "📉"
    side = "LONG 🟢" if s["dir"] == "LONG" else "SHORT 🔴"

    confidence = min(s["score"], 99)

    entry = s["price"]
    sl = s["sl"]
    tp1 = s["tp"]

    if s["dir"] == "LONG":
        tp2 = round(entry * 1.05, 6)
        sl_pct = round(((entry - sl) / entry) * 100, 2)
        tp1_pct = round(((tp1 - entry) / entry) * 100, 2)
        tp2_pct = round(((tp2 - entry) / entry) * 100, 2)
    else:
        tp2 = round(entry * 0.95, 6)
        sl_pct = round(((sl - entry) / entry) * 100, 2)
        tp1_pct = round(((entry - tp1) / entry) * 100, 2)
        tp2_pct = round(((entry - tp2) / entry) * 100, 2)

    rr = round(tp2_pct / sl_pct, 1) if sl_pct else 0

    return f"""
{medal} {direction_emoji}  NEW SIGNAL  ·  {confidence}% Confidence
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  🪙  {s['symbol']}
  📊  {side}
  ⏰  LIVE MARKET 🌍
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  💰  Entry    {entry}
  🛑  SL       {sl}  (-{sl_pct}%)
  🎯  TP1      {tp1}  (+{tp1_pct}%)
  🎯  TP2      {tp2}  (+{tp2_pct}%)
  📐  R : R    1 : {rr}
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
"""
def run_scan():

    results = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        outputs = list(executor.map(score_symbol, SYMBOLS))

    for result in outputs:
        if result:
            results.append(result)

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    top_signals = results[:2]

    if top_signals:

        for signal in top_signals:
            send(fmt(signal))

    else:
        send(
            f"⚪ NO STRONG SIGNAL\n{datetime.now()}"
        )

    send(
        f"SCAN DONE {datetime.now()}"
    )


# ================= MAIN =================

def main():

    print("AUTO 30M BOT STARTED")

    while True:

        try:

            run_scan()

        except Exception as e:

            print("[BOT ERROR]", e)

        time.sleep(1800)


# ================= START =================

if __name__ == "__main__":
    main()
