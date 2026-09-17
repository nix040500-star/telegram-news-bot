import os
import time
import requests
import feedparser
from google import genai
from google.genai.errors import ServerError

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
    target_entry = None
    for entry in feed.entries:
        if entry.link not in sent_urls:
            target_entry = entry
            break
            
    if not target_entry:
        print("새로운 기사 없음")
        return

    title = target_entry.title
    link = target_entry.link

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
너는 전문적인 크립토 애널리스트야. 아래 뉴스를 바탕으로 핵심 내용을 3개 단락으로 요약해줘.
마지막 줄에는 반드시 아래 링크를 포함할 것:
🔗 [기사 원문 보러가기]({link})

제목: {title}
링크: {link}
"""

    # 최신 권장 모델인 gemini-3.6-flash로 수정
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )

    if response:
        result_text = response.text
        if "[기사 원문 보러가기]" not in result_text:
            result_text += f"\n\n🔗 [기사 원문 보러가기]({link})"
        send_telegram(result_text)
        save_sent_url(link)

if __name__ == "__main__":
    main()
