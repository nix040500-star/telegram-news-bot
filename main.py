import os
import time
import requests
import feedparser
from google import genai
from google.genai.errors import ServerError

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def main():
    rss_url = "https://news.google.com/rss/search?q=비트코인+OR+암호화폐+OR+미국증시+OR+나스닥&hl=ko&gl=KR&ceid=KR:ko"
    headers = {"User-Agent": "Mozilla/5.0"}
    response_rss = requests.get(rss_url, headers=headers)
    feed = feedparser.parse(response_rss.content)
    
    if not feed.entries:
        print("에러: 수집된 뉴스 데이터가 없습니다.")
        return

    # 가장 최신 기사 딱 1개만 타겟팅
    latest_entry = feed.entries[0]
    title = latest_entry.title
    link = latest_entry.link

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
너는 전문적인 금융·크립토 애널리스트야. 아래 제공되는 단 하나의 뉴스 기사를 보고, **전문가가 직접 분석하고 풀어주는 듯한 자연스러운 산문체(줄글 형태)로 5~6줄 분량의 깊이 있는 요약 글**을 작성해줘.

[작성 규칙]
1. 기계적인 번호 매기기나 딱딱한 개조식을 절대 쓰지 말고, 자연스러운 문장 형태로 단락을 나누어 가독성 있게 작성할 것.
2. 이 뉴스가 시장에 갖는 의미와 배경을 전문가의 시각으로 깊이 있게 풀어낼 것.
3. 글의 맨 마지막 줄에 반드시 `🔗 [기사 원문 읽어보기]({link})` 형태로 링크를 남겨둘 것.

[대상 기사]
제목: {title}
링크: {link}
"""

    max_retries = 3
    response = None
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
            )
            break
        except ServerError as e:
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                raise e

    if response:
        send_telegram(response.text)

if __name__ == "__main__":
    main()
