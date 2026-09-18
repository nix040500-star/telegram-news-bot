import os
import time
import traceback
import requests
import feedparser
import google.generativeai as genai

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SENT_TITLES_FILE = "sent_titles.txt"

def load_sent_titles():
    if not os.path.exists(SENT_TITLES_FILE):
        return set()
    try:
        with open(SENT_TITLES_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except:
        return set()

def save_sent_title(title):
    try:
        with open(SENT_TITLES_FILE, "a", encoding="utf-8") as f:
            f.write(title + "\n")
    except Exception as e:
        print(f"파일 저장 중 에러: {e}")

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("🚨 TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다!")
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    res = requests.post(url, json=payload)
    
    print(f"텔레그램 전송 응답 코드: {res.status_code}")
    if res.status_code != 200:
        raise Exception(f"텔레그램 전송 실패! 응답 내용: {res.text}")

def is_similar(new_title, sent_titles):
    new_words = set(new_title.split())
    if not new_words:
        return False
        
    for sent in sent_titles:
        sent_words = set(sent.split())
        common_words = new_words.intersection(sent_words)
        if len(common_words) >= 4 or (len(common_words) / len(new_words) >= 0.5):
            return True
    return False

def main():
    try:
        print("--- 크립토 뉴스 봇 실행 시작 ---")
        
        if not GEMINI_API_KEY:
            raise ValueError("🚨 GEMINI_API_KEY가 설정되지 않았습니다!")

        print("1. RSS 뉴스 수집 시작...")
        rss_url = "https://news.google.com/rss/search?q=%EC%95%94%ED%98%B8%ED%99%94%ED%8F%90&hl=ko&gl=KR&ceid=KR:ko"
        headers = {"User-Agent": "Mozilla/5.0"}
        response_rss = requests.get(rss_url, headers=headers)
        
        if response_rss.status_code != 200:
            raise Exception(f"RSS 접근 실패! 상태 코드: {response_rss.status_code}")

        feed = feedparser.parse(response_rss.content)
        if not feed.entries:
            print("수집된 뉴스 없음")
            return

        sent_titles = load_sent_titles()
        
        target_entry = None
        for entry in feed.entries:
            title = entry.title
            if title in sent_titles or is_similar(title, sent_titles):
                continue
            target_entry = entry
            break
                
        if not target_entry:
            print("새로운 기사 없음 (모두 이미 보낸 기사)")
            return

        title = target_entry.title
        link = target_entry.link
        print(f"선택된 뉴스 제목: {title}")

        print("2. Gemini AI 요약 생성 시작...")
        genai.configure(api_key=GEMINI_API_KEY)
        
        prompt = f"""
너는 감각 있고 트렌디한 크립토 전문 텔레그램 채널 운영자야. 아래 최신 뉴스를 바탕으로 핵심만 짚어서 요약해줘.

[작성 스타일 및 규칙]
1. "안녕하세요"나 "전문가 관점에서..." 같은 AI 특유의 뻔한 인사말이나 서두 멘트는 절대 쓰지 말 것. 곧바로 본문 내용부터 시작할 것.
2. 지나치게 길지 않게 핵심 위주로 압축하되, 문장 흐름이 딱딱하지 않고 사람이 직접 쓴 것처럼 자연스럽고 읽기 편하게 작성할 것.
3. 글 중간중간 내용과 어울리는 이모티콘(💡, 🔥, 📊, ⚡ 등)을 **1~3개 정도만** 센스 있게 곁들일 것.
4. 글의 마지막 줄에는 반드시 아래 형식으로 링크를 포함할 것:
🔗 [기사 원문 보러가기]({link})

[대상 기사]
제목: {title}
링크: {link}
"""

        # 가장 안정적이고 호환성이 높은 표준 모델 지정
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)

        if response and response.text:
            result_text = response.text
            if "[기사 원문 보러가기]" not in result_text:
                result_text += f"\n\n🔗 [기사 원문 보러가기]({link})"
            
            print("3. 텔레그램 전송 중...")
            send_telegram(result_text)
            save_sent_title(title)
            print("모든 작업 완료!")

    except Exception as e:
        print("🚨 스크립트 실행 중 치명적 에러 발생:")
        traceback.print_exc()
        raise e

if __name__ == "__main__":
    main()
