import os
import time
import requests
import feedparser
from google import genai
from google.genai.errors import ServerError

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 이미 보낸 기사 링크를 기록할 파일 (중복 발송 방지용)
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
    rss_url = "https://news.google.com/rss/search?q=비트코인+OR+암호화폐+OR+미국증시+OR+나스닥+OR+리플+OR+이더리움+OR+코인+OR+연준+OR+금리+OR+트럼프+OR+일론머스크+OR+테슬라+OR+엔비디아&hl=ko&gl=KR&ceid=KR:ko"
    headers = {"User-Agent": "Mozilla/5.0"}
    response_rss = requests.get(rss_url, headers=headers)
    feed = feedparser.parse(response_rss.content)
    
    if not feed.entries:
        print("에러: 수집된 뉴스 데이터가 없습니다.")
        return

    sent_urls = load_sent_urls()
    
    # 아직 전송하지 않은 가장 최신 기사 1개만 타겟팅
    target_entry = None
    for entry in feed.entries:
        if entry.link not in sent_urls:
            target_entry = entry
            break
            
    if not target_entry:
        print("새로운 기사가 없습니다.")
        return

    title = target_entry.title
    link = target_entry.link

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 요청하신 예시 스타일과 링크 서식을 반영한 프롬프트
    prompt = f"""
너는 전문적인 금융·크립토 애널리스트야. 아래 제공되는 단 하나의 뉴스 기사를 바탕으로, 투자자들이 핵심 내용을 한눈에 파악할 수 있도록 3~4개의 단락으로 나누어 차분하고 신뢰감 있는 뉴스 분석 스타일로 작성해줘.

[작성 규칙]
1. 보내준 리플/규제 관련 예시 기사처럼, 객관적이면서도 시장에 미치는 의미를 자연스럽고 깊이 있게 서술할 것.
2. 기계적인 개조식이나 번호 매기기는 쓰지 말고, 자연스러운 줄글 형태로 단락을 구분할 것.
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
        except ServerError as e:
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                raise e

    if response:
        result_text = response.text
        
        # 혹시라도 AI가 링크 형식을 빼먹었을 경우를 대비한 안전 장치
        if "[기사 원문 보러가기]" not in result_text:
            result_text += f"\n\n🔗 [기사 원문 보러가기]({link})"
            
        send_telegram(result_text)
        
        # 전송 완료된 링크 저장 (다음 실행 때 중복 발송 차단)
        save_sent_url(link)

if name == "main":
    main()
