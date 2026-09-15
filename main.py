import os
import requests
import feedparser
from google import genai

# 1. 깃허브 Secrets에서 설정값 불러오기
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def main():
    # 구글 뉴스 RSS 피드 가져오기
    rss_url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(rss_url)
    
    news_list = []
    # 상위 5개 뉴스 제목 및 링크 수집
    for entry in feed.entries[:5]:
        news_list.append(f"- 제목: {entry.title}\n  링크: {entry.link}")
    
    news_text = "\n".join(news_list)
    
    # Gemini AI로 요약하기
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"다음 뉴스 목록을 보고, 텔레그램에 올리기 좋게 핵심만 3~4줄로 깔끔하게 요약해줘. 링크도 같이 남겨줘.\n\n{news_text}"
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    
    summary = response.text
    
    # 텔레그램 전송
    send_telegram(summary)

if __name__ == "__main__":
    main()
