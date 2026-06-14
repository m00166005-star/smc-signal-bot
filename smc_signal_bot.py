import os
import json
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
MIN_SCORE = 70

session = requests.Session()


# ================= DATA =================
def candles(symbol):
    try:
        r = session.get(
            f"{BASE}/api/v1/market/candles",
            params={"symbol": symbol, "type": TF},
            timeout=5
        )
        data = r.json().get("data", [])
        return [float(x[2]) for x in reversed(data[:80])]
    except:
        return []


# ================= INDICATORS (LIGHT) =================
def ema(prices, p):
    if len(prices) < p:
        return prices[-1] if prices else 0

    k = 2/(p+1)
    e = sum(prices[:p])/p

    for v in prices[p:]:
        e = v*k + e*(1-k)

    return e


def rsi(prices):
    if len(prices) < 15:
        return 50

    gains = 0
    losses = 0

    for i in range(-10, -1):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff

    if losses == 0:
        return 100

    rs = gains / losses
    return 100 - (100/(1+rs))


# ================= ANALYZE =================
def analyze(symbol):

    prices = candles(symbol)
    if not prices:
        return None

    price = prices[-1]

    e50 = ema(prices, 50)
    e200 = ema(prices, 200)
    r = rsi(prices)

    for direction in ["LONG", "SHORT"]:

        score = 0

        if direction == "LONG" and e50 > e200:
            score += 50

        if direction == "SHORT" and e50 < e200:
            score += 50

        if direction == "LONG" and r < 45:
            score += 30

        if direction == "SHORT" and r > 55:
            score += 30

        if score >= MIN_SCORE:

            sl = price * (0.98 if direction == "LONG" else 1.02)
            tp = price * (1.03 if direction == "LONG" else 0.97)

            return {
                "symbol": symbol,
                "dir": direction,
                "score": score,
                "price": price,
                "sl": sl,
                "tp": tp
            }

    return None


# ================= TELEGRAM =================
def send(msg):
    if not TOKEN or not CHAT_ID:
        return

    session.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg},
        timeout=5
    )


def format(sig):
    e = "🟢" if sig["dir"] == "LONG" else "🔴"

    return f"""{e} SIGNAL
{sig['symbol']} | {sig['dir']}
Score: {sig['score']}
Entry: {sig['price']}
SL: {sig['sl']}
TP: {sig['tp']}
{datetime.now()}
"""


# ================= MAIN =================
def worker(symbol):
    try:
        sig = analyze(symbol)
        if sig:
            send(format(sig))
    except:
        pass


def main():

    print("FAST BOT STARTED")

    while True:

        with ThreadPoolExecutor(max_workers=10) as exe:
            exe.map(worker, SYMBOLS)

        send(f"SCAN DONE {datetime.now()}")

        time.sleep(900)


if __name__ == "__main__":
    main()
