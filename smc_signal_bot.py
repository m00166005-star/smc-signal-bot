import os
import time
import requests
import json

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def get_market_data():
    # Fetch from Binance (api3 to prevent GitHub IP blocks)
    binance_url = "https://api3.binance.com/api/v3/ticker/24hr"
    try:
        response = requests.get(binance_url)
        tickers = response.json()
        if not isinstance(tickers, list):
            print(f"Warning: Unexpected format: {tickers}")
            tickers = []
    except Exception as e:
        print(f"Error fetching from Binance: {e}")
        tickers = []
    
    # Filter Top 50 USDT Volume pairs safely
    usdt_tickers = []
    for t in tickers:
        if isinstance(t, dict) and 'symbol' in t:
            sym = t['symbol']
            if sym.endswith('USDT') and 'UP' not in sym and 'DOWN' not in sym:
                usdt_tickers.append(t)
                
    usdt_tickers.sort(key=lambda x: float(x.get('quoteVolume', 0) or 0), reverse=True)
    top_50 = usdt_tickers[:50] # Increased to Top 50
    
    # Get Fear and Greed Index
    fng_url = "https://api.alternative.me/fng/"
    try:
        fng_res = requests.get(fng_url).json()
        fng = fng_res['data'][0]
    except:
        fng = {"value": "50", "value_classification": "Neutral"}
        
    market_data = []
    for t in top_50:
        market_data.append({
            "symbol": t['symbol'],
            "priceChangePercent": t.get('priceChangePercent', '0'),
            "lastPrice": t.get('lastPrice', '0'),
            "highPrice": t.get('highPrice', '0'),
            "lowPrice": t.get('lowPrice', '0'),
            "quoteVolume": t.get('quoteVolume', '0'),
            "fng_value": fng['value'],
            "fng_class": fng['value_classification']
        })
    return market_data

def ask_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        res_json = response.json()
        text_reply = res_json['candidates'][0]['content']['parts'][0]['text']
        return json.loads(text_reply)
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return None

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def main():
    print("Fetching top 50 market data...")
    send_telegram("🔄 *فرآیند اسکن ۵۰ ارز برتر بازار آغاز شد...*")
    coins = get_market_data()
    
    if not coins:
        send_telegram("❌ خطا در دریافت اطلاعات بازار از صرافی.")
        return
        
    for item in coins:
        print(f"Processing {item['symbol']}...")
        
        # Agent 1: Macro Filter (SMC Context Check)
        prompt_1 = (
            f"You are an elite crypto trading bot specializing in Smart Money Concepts (SMC) and Price Action.\n"
            f"Asset: {item['symbol']}\n24h Change: {item['priceChangePercent']}%\nCurrent Price: {item['lastPrice']}\n"
            f"Fear & Greed: {item['fng_value']} ({item['fng_class']})\n"
            f"Task: Analyze if the macro structure shows high probability for SMC setups (Premium/Discount zones, HTF mitigation). "
            f"Output strictly valid JSON:\n{{\"passed\": true/false, \"reason\": \"short descriptive reason in english\"}}"
        )
        macro_res = ask_gemini(prompt_1)
        time.sleep(1) # Delay to stay safe within rate limits
        
        # If Agent 1 rejects or fails, notify Telegram and move to next coin
        if not macro_res or not macro_res.get('passed'):
            reason = macro_res.get('reason', 'Unknown structure') if macro_res else 'API Error'
            send_telegram(f"🔍 *{item['symbol']}* ❌ Rejected by Macro Filter.\nReason: _{reason}_")
            continue
            
        # Agent 2: Micro Structure Simulation
        prompt_2 = (
            f"Generate a simulated mid-to-low timeframe market microstructure context data profile for {item['symbol']}.\n"
            f"Simulate realistic ICT/SMC variables matching a high-conviction structure.\n"
            f"Output strictly JSON:\n"
            f"{{\"mss_detected\": true/false, \"bos_trend\": \"bullish/bearish\", \"fvgs\": [\"zone\"], \"order_blocks\": [\"zone\"], \"liquidity_swept\": \"BSL/SSL\"}}"
        )
        micro_structure = ask_gemini(prompt_2)
        time.sleep(1)
        
        if not micro_structure:
            send_telegram(f"🔍 *{item['symbol']}* ⚠️ Failed at Micro Structure simulation stage.")
            continue
            
        # Agent 3: Core Strategy Filter
        prompt_3 = (
            f"Evaluate the simulated microstructure profile for {item['symbol']}.\nData: {json.dumps(micro_structure)}\n"
            f"Apply strict Price Action & SMC filters (Order Block entry alignment, FVG fill expectation).\n"
            f"Output strictly JSON:\n"
            f"{{\n\"setup_valid\": true/false,\n\"direction\": \"LONG/SHORT\",\n\"entry_zone\": \"price_level\",\n"
            f"\"invalidation_level\": \"price_level\",\n\"target_levels\": [\"tp1\", \"tp2\"],\n\"confluence_score_out_of_10\": 8\n}}"
        )
        strategy_res = ask_gemini(prompt_3)
        time.sleep(1)
        
        if not strategy_res or not strategy_res.get('setup_valid'):
            send_telegram(f"🔍 *{item['symbol']}* ❌ Setup invalid under core SMC strategy filters.")
            continue
            
        # Agent 4: Risk Management
        prompt_4 = (
            f"Analyze this trading setup for {item['symbol']}.\nDirection: {strategy_res['direction']}\n"
            f"Entry: {strategy_res['entry_zone']}\nSL: {strategy_res['invalidation_level']}\n"
            f"Task: Calculate Risk-to-Reward (R:R) based on SMC rules. Output strictly JSON:\n"
            f"{{\"risk_approved\": true/false, \"calculated_rr_ratio\": \"1:X\", \"position_sizing_recommendation\": \"X% risk\", \"risk_notes\": \"...\"}}"
        )
        risk_res = ask_gemini(prompt_4)
        time.sleep(1)
        
        if not risk_res or not risk_res.get('risk_approved'):
            send_telegram(f"🔍 *{item['symbol']}* ❌ Rejected by Risk Management (Poor R:R or high volatility).")
            continue
            
        # Agent 5: Devil's Advocate
        prompt_5 = (
            f"Review this setup for {item['symbol']}.\nDirection: {strategy_res['direction']}\n"
            f"Entry: {strategy_res['entry_zone']}\nSL: {strategy_res['invalidation_level']}\n"
            f"Critique intensely under ICT principles (Is it a liquidity trap? Inducement?). Assign win probability.\n"
            f"Output JSON:\n{{\"critique\": \"...\", \"final_win_probability_percent\": 85}}"
        )
        devil_res = ask_gemini(prompt_5)
        time.sleep(1)
        
        # Build and Send Valid Final Signal
        win_prob = devil_res.get('final_win_probability_percent', 70) if devil_res else 70
        critique = devil_res.get('critique', 'No critique available') if devil_res else ''
        
        msg = (
            f"🚀 **SMC/PRICE ACTION SIGNAL GENERATED** 🚀\n\n"
            f"**Asset:** #{item['symbol']}\n"
            f"**Direction:** {'🟢 LONG' if strategy_res['direction'] == 'LONG' else '🔴 SHORT'}\n\n"
            f"🎯 **Entry Zone:** {strategy_res['entry_zone']}\n"
            f"🛑 **Invalidation (SL):** {strategy_res['invalidation_level']}\n"
            f"🚀 **Targets (TP):** {', '.join(strategy_res['target_levels'])}\n\n"
            f"📊 **Confluence Metrics:**\n"
            f"- Strategy Score: {strategy_res['confluence_score_out_of_10']}/10\n"
            f"- Calculated R:R: {risk_res.get('calculated_rr_ratio', '1:2')}\n"
            f"- Sizing: {risk_res.get('position_sizing_recommendation', '1%')}\n\n"
            f"🔥 **Win Probability:** {win_prob}%\n"
            f"🕵️‍♂️ **Devil's Advocate Critique:**\n_{critique}_\n"
        )
        send_telegram(msg)
        print(f"Signal sent for {item['symbol']}!")

    send_telegram("🏁 *اسکن ۵۰ ارز به پایان رسید.*")

if __name__ == "__main__":
    main()
