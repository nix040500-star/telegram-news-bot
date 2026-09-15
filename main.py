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
    # 코인 및 미국 증시 뉴스 RSS 피드 가져오기
    rss_url = "https://news.google.com/rss/search?q=비트코인+OR+암호화폐+OR+미국증시+OR+나스닥&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(rss_url)
    
    news_list = []
    # 상위 5개 뉴스 제목 및 링크 수집
    for i, entry in enumerate(feed.entries[:5], 1):
        news_list.append(f"[{i}] 제목: {entry.title}\n링크: {entry.link}")
    
    news_text = "\n\n".join(news_list)
    
    # Gemini AI로 요약하기 (출력 템플릿 지정)
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
다음 뉴스들을 분석해서 핵심 내용을 한국어로 사람이 쓴 것처럼 이모티콘 없이 자연스럽고 깔끔하게 요약해줘.

[출력 형식 가이드]
1. 전체 주요 뉴스 브리핑 (4~6줄 요약)
2. 각 기사별 핵심 내용 및 참고 링크 목록

[수집된 뉴스 데이터]
{news_text}
"""
    
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    
    summary = response.text
    
    # 텔레그램 전송
    send_telegram(summary)

if __name__ == "__main__":
    main()
