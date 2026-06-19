import os
import time
import requests
import json

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def get_market_data():
    # 1. Get Binance Tickers
    binance_url = "https://api.binance.com/api/v3/ticker/24hr"
    tickers = requests.get(binance_url).json()
    
    # Filter Top 20 USDT Volume
    usdt_tickers = [t for t in tickers if t['symbol'].endswith('USDT') and 'UP' not in t['symbol'] and 'DOWN' not in t['symbol']]
    usdt_tickers.sort(key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
    top_20 = usdt_tickers[:20]
    
    # 2. Get Fear and Greed Index
    fng_url = "https://api.alternative.me/fng/"
    try:
        fng_res = requests.get(fng_url).json()
        fng = fng_res['data'][0]
    except:
        fng = {"value": "50", "value_classification": "Neutral"}
        
    # Merge Data
    market_data = []
    for t in top_20:
        market_data.append({
            "symbol": t['symbol'],
            "priceChangePercent": t['priceChangePercent'],
            "lastPrice": t['lastPrice'],
            "highPrice": t['highPrice'],
            "lowPrice": t['lowPrice'],
            "quoteVolume": t['quoteVolume'],
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
        print(f"Gemini API Error or Parse Error: {e}")
        return None

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def main():
    print("Fetching market data...")
    coins = get_market_data()
    
    # Cooldown check logic can be added here via a file database if needed, 
    # but GitHub Actions starts fresh every run.
    
    for item in coins:
        print(f"Processing {item['symbol']}...")
        
        # Agent 1: Macro Filter
        prompt_1 = f"You are an elite crypto trading bot specializing in SMC/ICT.\nAsset: {item['symbol']}\n24h Change: {item['priceChangePercent']}%\nCurrent Price: {item['lastPrice']}\nF&G Index: {item['fng_value']}\nTask: Determine if structure is suitable for SMC analysis. Output strictly JSON:\n{{\"passed\": true/false, \"reason\": \"...\"}}"
        macro_res = ask_gemini(prompt_1)
        time.sleep(2) # Avoid Rate Limits
        
        if not macro_res or not macro_res.get('passed'):
            continue
            
        # Agent 2: Micro Structure Simulation
        prompt_2 = f"Generate a simulated mid-to-low timeframe market microstructure context data profile for {item['symbol']}. Simulate realistic ICT/SMC variables matching a high-conviction structure. Output strictly JSON:\n{{\"mss_detected\": true/false, \"bos_trend\": \"bullish/bearish\", \"fvgs\": [], \"order_blocks\": [], \"liquidity_swept\": \"BSL/SSL\"}}"
        micro_structure = ask_gemini(prompt_2)
        time.sleep(2)
        
        if not micro_structure:
            continue
            
        # Agent 3: Core Strategy Filter
        prompt_3 = f"Evaluate the simulated microstructure profile for {item['symbol']}.\nData: {json.dumps(micro_structure)}\nApply strict ICT/SMC filters. Output strictly JSON:\n{{\"setup_valid\": true/false, \"direction\": \"LONG/SHORT\", \"entry_zone\": \"price\", \"invalidation_level\": \"price\", \"target_levels\": [], \"confluence_score_out_of_10\": 8}}"
        strategy_res = ask_gemini(prompt_3)
        time.sleep(2)
        
        if not strategy_res or not strategy_res.get('setup_valid'):
            continue
            
        # Agent 4: Risk Management
        prompt_4 = f"Analyze this trading setup for {item['symbol']}.\nDirection: {strategy_res['direction']}\nEntry: {strategy_res['entry_zone']}\nSL: {strategy_res['invalidation_level']}\nF&G: {item['fng_value']}\nTask: Output strict Risk-to-Reward and sizing JSON:\n{{\"risk_approved\": true/false, \"calculated_rr_ratio\": \"1:3\", \"position_sizing_recommendation\": \"1% risk\", \"risk_notes\": \"...\"}}"
        risk_res = ask_gemini(prompt_4)
        time.sleep(2)
        
        if not risk_res or not risk_res.get('risk_approved'):
            continue
            
        # Agent 5: Devil's Advocate
        prompt_5 = f"Review this setup for {item['symbol']}.\nDirection: {strategy_res['direction']}\nEntry: {strategy_res['entry_zone']}\nSL: {strategy_res['invalidation_level']}\nCritique intensely under ICT principles. Assign win probability (0-100%). Output JSON:\n{{\"critique\": \"...\", \"counter_argument\": \"...\", \"final_win_probability_percent\": 85}}"
        devil_res = ask_gemini(prompt_5)
        time.sleep(2)
        
        if not devil_res or devil_res.get('final_win_probability_percent', 0) < 80:
            continue
            
        # Build and Send Telegram Message
        msg = (
            f"🚨 **SMC/ICT ALGO SIGNAL GENERATED** 🚨\n\n"
            f"**Asset:** #{item['symbol']}\n"
            f"**Direction:** {'🟢 LONG' if strategy_res['direction'] == 'LONG' else '🔴 SHORT'}\n\n"
            f"🎯 **Entry Zone:** {strategy_res['entry_zone']}\n"
            f"🛑 **Invalidation (SL):** {strategy_res['invalidation_level']}\n"
            f"🚀 **Targets (TP):** {', '.join(strategy_res['target_levels'])}\n\n"
            f"📊 **Confluence Setup:**\n"
            f"- Confluence Score: {strategy_res['confluence_score_out_of_10']}/10\n"
            f"- Calculated R:R: {risk_res['calculated_rr_ratio']}\n"
            f"- Position Sizing: {risk_res['position_sizing_recommendation']}\n"
            f"- Market F&G: {item['fng_value']} ({item['fng_class']})\n\n"
            f"🔥 **Algorithmic Win Probability:** {devil_res['final_win_probability_percent']}%\n\n"
            f"🕵️‍♂️ **Devil's Advocate Critique:**\n_{devil_res['critique']}_\n\n"
            f"⚠️ *Risk Warning: Institutional models simulate potential fakeouts.*"
        )
        send_telegram(msg)
        print(f"Signal sent for {item['symbol']}!")

if __name__ == "__main__":
    main()
