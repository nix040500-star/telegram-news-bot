import os
import traceback
import requests
import feedparser
import urllib.parse
import email.utils
from datetime import datetime, timezone, timedelta
from google import genai

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SENT_FILE = "sent_urls.txt"


def load_sent_urls():
    if not os.path.exists(SENT_FILE):
        return set()

    with open(SENT_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_sent_url(url):
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 텔레그램 설정 없음")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:
        res = requests.post(url, json=payload, timeout=30)

        print("텔레그램 응답:", res.status_code)

        if res.status_code != 200:
            print(res.text)
            return False

        return True

    except Exception as e:
        print("❌ 텔레그램 오류:", e)
        return False


def main():

    print("=== 🚀 크립토 최신 뉴스 봇 실행 ===")

    try:
        if not GEMINI_API_KEY:
            print("❌ GEMINI_API_KEY 없음")
            return

        # ─────────────────────
        # 1. Google News 수집
        # ─────────────────────

        keyword = urllib.parse.quote(
            "암호화폐 OR 비트코인 OR 이더리움 OR 리플"
        )

        rss_url = (
            f"https://news.google.com/rss/search?"
            f"q={keyword}&hl=ko&gl=KR&ceid=KR:ko"
        )

        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(
            rss_url,
            headers=headers,
            timeout=20
        )

        if response.status_code != 200:
            print("❌ RSS 접근 실패")
            return

        feed = feedparser.parse(response.content)

        if not feed.entries:
            print("❌ 뉴스 없음")
            return

        # ─────────────────────
        # 2. 최신순 정렬
        # ─────────────────────

        def get_date(entry):

            try:
                return email.utils.parsedate_to_datetime(
                    entry.published
                )

            except Exception:
                return datetime.min.replace(
                    tzinfo=timezone.utc
                )

        entries = sorted(
            feed.entries,
            key=get_date,
            reverse=True
        )

        sent_urls = load_sent_urls()

        now = datetime.now(timezone.utc)

        target_entry = None

        # ─────────────────────
        # 3. 최근 1시간 + 미전송 기사
        # ─────────────────────

        for entry in entries:

            try:
                published = email.utils.parsedate_to_datetime(
                    entry.published
                )

            except Exception:
                continue

            # 1시간 지난 뉴스 제외
            if now - published > timedelta(hours=1):
                continue

            # 이미 보낸 뉴스 제외
            if entry.link in sent_urls:
                continue

            target_entry = entry
            break

        if target_entry is None:
            print("✅ 새로 보낼 최신 뉴스가 없습니다.")
            return

        title = target_entry.title
        link = target_entry.link

        print("📰 선택 뉴스:", title)

        # ─────────────────────
        # 4. Gemini 요약
        # ─────────────────────

        client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        prompt = f"""
너는 암호화폐 뉴스 전문 요약 에디터다.

아래 기사를 모바일 텔레그램에서
스크롤을 거의 하지 않고 읽을 수 있도록 짧게 요약한다.

[규칙]

- 인사말 없이 바로 핵심 내용부터 시작한다.
- 본문은 짧은 2문단으로 작성한다.
- 어려운 전문용어는 쉽게 풀어서 쓴다.
- 불필요한 배경 설명과 반복은 제거한다.
- 기사에 없는 사실은 절대 추가하지 않는다.
- 중요한 코인명, 기업명, 수치는 유지한다.
- 과도한 이모티콘은 사용하지 않는다.

마지막은 반드시 다음 형식으로 작성한다.

📌 짧게 말씀드리면..
기사 전체 핵심을 한 문장으로 요약한다.

🔗 [기사 원문 보러가기]({link})

[기사]

제목: {title}

링크: {link}
"""

        result = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt
        )

        if not result or not result.text:
            print("❌ Gemini 응답 없음")
            return

        text = result.text

        # 링크 누락 방지
        if "[기사 원문 보러가기]" not in text:

            text += (
                f"\n\n🔗 [기사 원문 보러가기]"
                f"({link})"
            )

        # ─────────────────────
        # 5. Telegram 전송
        # ─────────────────────

        if send_telegram(text):

            print("🎉 뉴스 전송 성공")

            # 성공한 기사만 기록
            save_sent_url(link)

        else:

            print("❌ 뉴스 전송 실패")

    except Exception:

        print("💥 오류 발생")
        traceback.print_exc()


if __name__ == "__main__":
    main()
