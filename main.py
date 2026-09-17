import os
import time
import requests
import feedparser
import subprocess
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai.errors import ServerError, APIError

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SENT_TITLES_FILE = "sent_titles.txt"

def load_sent_titles():
    if not os.path.exists(SENT_TITLES_FILE):
        return set()
    with open(SENT_TITLES_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_title_and_git_commit(title):
    with open(SENT_TITLES_FILE, "a", encoding="utf-8") as f:
        f.write(title + "\n")
    
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", SENT_TITLES_FILE], check=True)
        subprocess.run(["git", "commit", "-m", "Update sent_titles.txt [skip ci]"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("중복 방지 기록 깃허브 저장 완료")
    except Exception as e:
        print(f"Git 커밋 중 오류 발생 (무시 가능): {e}")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

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
        subprocess.run(["git", "pull"], check=True)
    except:
        pass

    # 구글 뉴스 RSS URL (언어 한국어, 최신순 정렬 유도를 위한 파라미터 포함)
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

    sent_titles = load_sent_titles()
    
    # 현재 시간 (UTC 기준)
    now_utc = datetime.now(timezone.utc)
    
    target_entry = None
    for entry in feed.entries:
        title = entry.title
        
        # 1. 이미 보낸 뉴스이거나 비슷한 제목이면 패스
        if title in sent_titles or is_similar(title, sent_titles):
            continue
            
        # 2. 기사 발행 시간 검사 (최근 24시간 이내 기사만 허용)
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            from time import mktime
            pub_date = datetime.fromtimestamp(mktime(entry.published_parsed), timezone.utc)
            # 현재 시간과 기사 발행 시간의 차이가 24시간 이내인지 확인
            if (now_utc - pub_date) > timedelta(hours=24):
                print(f"너무 오래된 기사 스킵: {title}")
                continue
                
        target_entry = entry
        break
            
    if not target_entry:
        print("24시간 이내의 새로운 기사 없음")
        return

    title = target_entry.title
    link = target_entry.link

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
너는 전문적인 크립토 애널리스트야. 아래 최신 뉴스를 바탕으로 핵심 내용을 요약해줘.

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
        save_sent_title_and_git_commit(title)

if __name__ == "__main__":
    main()
