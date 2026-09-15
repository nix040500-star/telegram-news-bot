import os
from datetime import datetime
import pytz
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def main():
    price_url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,binancecoin,solana,ripple,dogecoin&vs_currencies=usd&include_24hr_change=true"
    global_url = "https://api.coingecko.com/api/v3/global"
    fng_url = "https://api.alternative.me/fng/"
    
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        prices_res = requests.get(price_url, headers=headers).json()
        global_data = requests.get(global_url, headers=headers).json().get("data", {})
        fng_data = requests.get(fng_url, headers=headers).json().get("data", [{}])[0]
    except Exception as e:
        print(f"API 호출 에러: {e}")
        return

    coins = [
        ("BTC", "bitcoin", "₿"),
        ("ETH", "ethereum", "◆"),
        ("BNB", "binancecoin", "🔷"),
        ("SOL", "solana", "◎"),
        ("XRP", "ripple", "🔵"),
        ("DOGE", "dogecoin", "🟠")
    ]
    
    coin_lines = []
    for symbol, coin_id, icon in coins:
        data = prices_res.get(coin_id, {})
        price = data.get("usd")
        change = data.get("usd_24h_change")
        
        if price is not None and change is not None:
            emoji = "🟢" if change >= 0 else "🔴"
            price_str = f"${price:,.2f}" if price >= 1 else f"${price:.4f}"
            change_str = f"{change:+.2f}%"
            coin_lines.append(f"{icon} {symbol} {price_str} {emoji} {change_str}")
        else:
            coin_lines.append(f"{icon} {symbol} N/A ⚪ N/A")

    market_cap_usd = global_data.get("total_market_cap", {}).get("usd", 0)
    market_cap_t = market_cap_usd / 1e12
    btc_dominance = global_data.get("market_cap_percentage", {}).get("btc", 0)
    
    fng_value = fng_data.get("value", "N/A")
    fng_class = fng_data.get("value_classification", "N/A").upper()

    kst = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(kst)
    time_str = now_kst.strftime('%m/%d %H:%M GMT+9')

    message = f"""🪙 **CRYPTO MARKET · LIVE**
`{time_str}`
━━━━━━━━━━━━━━━━━━
"""
    message += "\n\n".join(coin_lines)
    message += f"""
━━━━━━━━━━━━━━━━━━
🌐 시가총액 ${market_cap_t:.2f}T

₿ BTC Dominance {btc_dominance:.2f}% 

😱 Fear & Greed {fng_value} · {fng_class} 
🟠 MARKET BIAS · BEARISH ↘
● LIVE · `{time_str}`"""

    send_telegram(message)

if __name__ == "__main__":
    main()
