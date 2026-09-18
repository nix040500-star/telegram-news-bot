import os
import time
import traceback
import requests
import feedparser
import google.generativeai as genai
import urllib.parse

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
        print("🚨 에러: TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 비어있습니다!")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    
    try:
        res = requests.post(url, json=payload)
        print(f"텔레그램 전송 응답 코드: {res.status_code}")
        if res.status_code != 200:
            print(f"텔레그램 전송 실패 상세 내용: {res.text}")
            return False
        return True
    except Exception as e:
        print(f"텔레그램 요청 중 예외 발생: {e}")
        return False

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
            print("🚨 에러: GEMINI_API_KEY가 설정되지 않았습니다!")
            return

        print("1. 실시간 RSS 뉴스 수집 시작...")
        # 실시간성이 높은 구글 뉴스 RSS 표준 쿼리 적용
        keyword = urllib.parse.quote("암호화폐")
        rss_url = f"https://news.google.com/rss/search?q={keyword}&hl=ko&gl=KR&ceid=KR:ko"
        
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response_rss = requests.get(rss_url, headers=headers)
        
        print(f"RSS 응답 코드: {response_rss.status_code}")
        if response_rss.status_code != 200:
            print(f"RSS 접근 실패 상태 코드: {response_rss.status_code}")
            return

        feed = feedparser.parse(response_rss.content)
        print(f"수집된 전체 기사 개수: {len(feed.entries)}")
        
        if not feed.entries:
            print("수집된 뉴스 없음")
            return

        sent_titles = load_sent_titles()
        
        target_entry = None
        for i, entry in enumerate(feed.entries[:5]):
            print(f"[{i+1번째 기사 제목]: {entry.title}")

        for entry in feed.entries:
            title = entry.title
            if title in sent_titles or is_similar(title, sent_titles):
                continue
            target_entry = entry
            break
                
        if not target_entry:
            print("새로운 기사 없음 (최근 기사들이 모두 이미 발송된 기록에 있음)")
            return

        title = target_entry.title
        link = target_entry.link
        print(f"✨ 최종 선택된 새로운 뉴스 제목: {title}")

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

        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)

        if response and response.text:
            result_text = response.text
            if "[기사 원문 보러가기]" not in result_text:
                result_text += f"\n\n🔗 [기사 원문 보러가기]({link})"
            
            print("3. 텔레그램 전송 중...")
            success = send_telegram(result_text)
            if success:
                save_sent_title(title)
                print("모든 작업 성공적으로 완료!")
            else:
                print("텔레그램 전송 실패로 인해 히스토리 저장을 건너뜁니다.")
        else:
            print("Gemini AI로부터 응답을 받지 못했습니다.")

    except Exception as e:
        print("🚨 치명적인 예외 발생:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
