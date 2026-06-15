import os
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BASE = "https://api.kucoin.com"

SYMBOLS = [
"BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
"DOGE-USDT","ADA-USDT","TRX-USDT","AVAX-USDT","LINK-USDT",
"DOT-USDT","MATIC-USDT","LTC-USDT","BCH-USDT","ATOM-USDT",
"NEAR-USDT","APT-USDT","ETC-USDT","UNI-USDT","FIL-USDT"
]

TF = "1hour"
session = requests.Session()

# جلوگیری از تکرار سیگنال
last_sent = {}


# ================= DATA =================
def candles(symbol):
    try:
        r = session.get(
            f"{BASE}/api/v1/market/candles",
            params={"symbol": symbol, "type": TF},
            timeout=5
        )
        data = r.json().get("data", [])
        return [float(x[2]) for x in reversed(data[:100])]
    except:
        return []


# ================= INDICATORS =================
def ema(data, p):
    if len(data) < p:
        return data[-1] if data else 0

    k = 2/(p+1)
    e = sum(data[:p])/p

    for v in data[p:]:
        e = v*k + e*(1-k)

    return e


def rsi(data):
    if len(data) < 20:
        return 50

    gain = 0
    loss = 0

    for i in range(-14, -1):
        diff = data[i] - data[i-1]
        if diff > 0:
            gain += diff
        else:
            loss -= diff

    if loss == 0:
        return 100

    rs = gain / loss
    return 100 - (100/(1+rs))


def volatility(data):
    return max(data[-15:]) - min(data[-15:])


# ================= SCORING =================
def score_symbol(symbol):

    prices = candles(symbol)
    if not prices:
        return None

    price = prices[-1]

    e50 = ema(prices, 50)
    e200 = ema(prices, 200)
    r = rsi(prices)
    vol = volatility(prices)

    long = 0
    short = 0

    if e50 > e200:
        long += 40
    else:
        short += 40

    if r < 40:
        long += 25
    elif r > 60:
        short += 25

    if vol > price * 0.012:
        long += 15
        short += 15

    if prices[-1] > prices[-2]:
        long += 10
    else:
        short += 10

    if long < 55 and short < 55:
        return None

    direction = "LONG" if long >= short else "SHORT"
    score = max(long, short)

    return {
        "symbol": symbol,
        "dir": direction,
        "score": score,
        "price": price,
        "sl": price * (0.98 if direction == "LONG" else 1.02),
        "tp": price * (1.03 if direction == "LONG" else 0.97)
    }


# ================= TELEGRAM =================
def send(msg):
    if TOKEN and CHAT_ID:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg},
            timeout=5
        )


def fmt(s):

    mood = "💎" if s["score"] > 80 else "🔥" if s["score"] > 65 else "⚡"
    arrow = "📈" if s["dir"] == "LONG" else "📉"
    side = "🟢 LONG" if s["dir"] == "LONG" else "🔴 SHORT"

    return f"""{mood} PRO SIGNAL {arrow}
━━━━━━━━━━━━━━
{side} | {s['symbol']}
🏆 Score: {s['score']}
💰 Entry: {s['price']:.6f}
🛑 SL: {s['sl']:.6f}
🎯 TP: {s['tp']:.6f}
━━━━━━━━━━━━━━
🕒 {datetime.now().strftime('%H:%M:%S')}
"""


# ================= MAIN =================
def run_scan():

    results = []

    with ThreadPoolExecutor(max_workers=10) as ex:
        outs = list(ex.map(score_symbol, SYMBOLS))

    for o in outs:
        if o:
            results.append(o)

    results = sorted(results, key=lambda x: x["score"], reverse=True)

    top2 = results[:2]

    now_key = datetime.now().strftime("%Y-%m-%d-%H")

    for t in top2:

        key = f"{t['symbol']}-{t['dir']}"

        # جلوگیری از تکرار پشت سر هم
        if last_sent.get(key) == now_key:
            continue

        last_sent[key] = now_key

        send(fmt(t))

    send(f"SCAN DONE {datetime.now()}")


def main():

    print("PRO BOT RUNNING")

    while True:
        run_scan()
        time.sleep(1800)  # 30 min


if name == "main":
    main()
