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
    # 무료 환율 API 호출 (USD 기준)
    api_url = "https://open.er-api.com/v6/latest/USD"
    
    try:
        res = requests.get(api_url).json()
        rates = res.get("rates", {})
    except Exception as e:
        print(f"환율 API 호출 에러: {e}")
        return

    # 요청하신 통화 목록 및 국기 이모지 매핑
    currencies = [
        ("KRW", "🇰🇷", "{:,.2f}"),
        ("JPY", "🇯🇵", "{:,.2f}"),
        ("CNY", "🇨🇳", "{:.4f}"),
        ("HKD", "🇭🇰", "{:.4f}"),
        ("SGD", "🇸🇬", "{:.4f}"),
        ("THB", "🇹🇭", "{:.3f}"),
        ("PHP", "🇵🇭", "{:.3f}"),
        ("VND", "🇻🇳", "{:,.2f}"),
        ("IDR", "🇮🇩", "{:,.2f}"),
        ("MYR", "🇲🇾", "{:.4f}"),
        ("TWD", "🇹🇭", "{:.2f}"), # 표기용 심볼
        ("AUD", "🇦🇺", "{:.2f}"),
        ("GBP", "🇬🇧", "{:.2f}"),
        ("EUR", "🇪🇺", "{:.2f}")
    ]
    
    fx_lines = []
    for code, flag, fmt in currencies:
        rate = rates.get(code)
        if rate is not None:
            formatted_rate = fmt.format(rate)
            fx_lines.append(f"{flag} {code} {formatted_rate}")
        else:
            fx_lines.append(f"{flag} {code} N/A")

    # 한국 시간(KST) 타임스탬프 생성
    kst = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(kst)
    date_str = now_kst.strftime('%Y.%m.%d')
    time_str = now_kst.strftime('%H:%M')

    # 요청하신 템플릿 형태로 조합
    message = f"""💱 **GLOBAL FX BRIEF**
USD 기준 · 주요 통화 최신 환율
━━━━━━━━━━━━━━━━
"""
    message += "\n\n".join(fx_lines)
    message += f"""
━━━━━━━━━━━━━━━━
📌 BASE CURRENCY USD

🕐 UPDATE {date_str} · {time_str} (GMT+9)

🌏 TIMEZONE GMT+9

📊 REFERENCE 실시간 FX · ExchangeRate-API
Market Note
달러 대비 주요 아시아 및 글로벌 통화의 실시간 환율 정보입니다. 
※ 실제 환전 시에는 은행별 매매기준율, 현찰 환율, 송금 환율 및 수수료에 따라 실제 적용 금액이 달라질 수 있습니다."""

    send_telegram(message)

if __name__ == "__main__":
    main()
