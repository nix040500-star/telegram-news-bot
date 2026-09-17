import os
import time
import requests
import feedparser
from google import genai
from google.genai.errors import ServerError, APIError

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SENT_URLS_FILE = "sent_urls.txt"

def load_sent_urls():
    if not os.path.exists(SENT_URLS_FILE):
        return set()
    with open(SENT_URLS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_url(url):
    with open(SENT_URLS_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def main():
    rss_url = "https://news.google.com/rss/search?q=%EC%95%94%ED%98%B8%ED%99%94%ED%8F%90&hl=ko&gl=KR&ceid=KR:ko"
    headers = {"User-Agent": "Mozilla/5.0"}
    response_rss = requests.get(rss_url, headers=headers)
    
    if response_rss.status_code != 200:
        print("RSS 접근 실패")
        return

    feed = feedparser.parse(response_rss.content)
    if not feed.entries:
        print("수집된 뉴스 없음")
        return

    sent_urls = load_sent_urls()
    
    # 새로운 기사를 찾되, 이미 보낸 링크뿐만 아니라 제목 키워드 중복까지 체크합니다.
    target_entry = None
    for entry in feed.entries:
        # 1차 체크: 링크가 이미 sent_urls에 있는지 확인
        if entry.link in sent_urls:
            continue
            
        # 2차 체크: 제목이 너무 겹치는지 간단히 확인 (원한다면 추가 가능)
        target_entry = entry
        break
            
    if not target_entry:
        print("새로운 기사 없음")
        return

    title = target_entry.title
    link = target_entry.link

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
너는 전문적인 크립토 애널리스트야. 아래 뉴스를 바탕으로 핵심 내용을 요약해줘.

[엄격한 작성 규칙]
1. "전문 크립토 애널리스트 시각에서 정리한..." 같은 인사말이나 서두 멘트는 절대 쓰지 말 것. 곧바로 본문 분석 내용부터 시작할 것.
2. 기사의 핵심 내용을 3개 단락으로 나누어 차분하고 신뢰감 있는 뉴스 분석 스타일로 작성할 것.
3. 글의 마지막 줄에는 반드시 아래 형식으로 링크를 포함할 것:
🔗 [기사 원문 보러가기]({link})

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
        except (ServerError, APIError) as e:
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                raise e

    if response:
        result_text = response.text
        if "[기사 원문 보러가기]" not in result_text:
            result_text += f"\n\n🔗 [기사 원문 보러가기]({link})"
        send_telegram(result_text)
        save_sent_url(link)

if __name__ == "__main__":
    main()
