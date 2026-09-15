import os
import time
import requests
import feedparser
from google import genai
from google.genai.errors import ServerError

# 1. 깃허브 Secrets에서 설정값 불러오기
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    response = requests.post(url, json=payload)
    print(f"텔레그램 전송 응답: {response.status_code}")

def main():
    # 코인 및 미국 증시 뉴스 RSS 피드 가져오기
    rss_url = "https://news.google.com/rss/search?q=비트코인+OR+암호화폐+OR+미국증시+OR+나스닥&hl=ko&gl=KR&ceid=KR:ko"
    
    headers = {"User-Agent": "Mozilla/5.0"}
    response_rss = requests.get(rss_url, headers=headers)
    feed = feedparser.parse(response_rss.content)
    
    news_items = []
    for entry in feed.entries[:5]:
        news_items.append({"title": entry.title, "link": entry.link})
    
    if not news_items:
        print("에러: 수집된 뉴스 데이터가 없습니다.")
        send_telegram("⚠️ 뉴스 요약 봇: 뉴스를 수집하는 데 실패했습니다.")
        return

    # Gemini AI 클라이언트 설정
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
너는 전문적인 금융·크립토 애널리스트야. 아래 제공되는 뉴스 기사 목록을 보고, 각 기사별로 **전문가가 직접 분석하고 풀어주는 듯한 자연스러운 문체로 5~6줄 정도의 깊이 있는 요약 글**을 작성해줘.

[작성 규칙]
1. 기계적인 개조식(1번, 2번 같은 딱딱한 형태)보다는 **자연스럽고 부드러운 산문체(줄글 형태)**로 5~6줄 분량으로 상세히 서술할 것.
2. 왜 이 뉴스가 중요한지, 시장에 어떤 의미를 갖는지 전문가의 시각을 담아낼 것.
3. 각 기사 본문 설명이 끝난 바로 아래에 `🔗 [기사 원문 읽어보기](링크주소)` 형태로 링크를 첨부할 것.

[수집된 뉴스 데이터 목록]
"""

    for idx, item in enumerate(news_items, 1):
        prompt += f"\n--- [기사 {idx}] ---\n제목: {item['title']}\n링크: {item['link']}\n"

    # [핵심] 503 서버 과부하 에러 발생 시 최대 3번까지 재시도하는 로직
    max_retries = 3
    response = None
    
    for attempt in range(max_retries):
        try:
            print(f"AI 요약 요청 시도 중... ({attempt + 1}/{max_retries})")
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
            )
            break # 성공하면 반복문 탈출
        except ServerError as e:
            print(f"서버 과부하(503) 발생: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5 # 5초, 10초 대기
                print(f"{wait_time}초 후 재시도합니다...")
                time.sleep(wait_time)
            else:
                print("최대 재시도 횟수를 초과했습니다.")
                raise e

    if response:
        summary = response.text
        # 텔레그램 전송
        send_telegram(summary)

if __name__ == "__main__":
    main()
