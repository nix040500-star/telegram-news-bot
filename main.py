import os
import traceback
import requests
import feedparser
import urllib.parse
import email.utils
from datetime import datetime, timezone, timedelta
from google import genai

# =========================================================
# 환경변수
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SENT_FILE = "sent_urls.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    )
}


# =========================================================
# 이미 보낸 뉴스 불러오기
# =========================================================

def load_sent_urls():
    if not os.path.exists(SENT_FILE):
        return set()

    with open(SENT_FILE, "r", encoding="utf-8") as f:
        return {
            line.strip()
            for line in f
            if line.strip()
        }


# =========================================================
# 전송 성공 URL 저장
# =========================================================

def save_sent_url(url):
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


# =========================================================
# Google News 링크 → 실제 기사 링크 확인
# =========================================================

def resolve_article_url(entry):

    google_link = entry.link

    try:
        response = requests.get(
            google_link,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True
        )

        final_url = response.url

        # 실제 언론사 URL로 이동했으면 사용
        if (
            final_url
            and final_url.startswith("http")
            and "news.google.com" not in final_url
        ):
            return final_url

    except Exception as e:
        print("⚠️ 실제 기사 URL 확인 실패:", e)

    # 실제 URL 확인 실패 시
    # 해당 기사 Google News 주소를 그대로 사용
    return google_link


# =========================================================
# Telegram 전송
# =========================================================

def send_telegram(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 텔레그램 설정 없음")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:

        res = requests.post(
            url,
            json=payload,
            timeout=30
        )

        print(
            "텔레그램 응답:",
            res.status_code
        )

        if res.status_code != 200:
            print(res.text)
            return False

        return True

    except Exception as e:

        print(
            "❌ 텔레그램 오류:",
            e
        )

        return False


# =========================================================
# 뉴스 날짜 가져오기
# =========================================================

def get_date(entry):

    try:

        date = email.utils.parsedate_to_datetime(
            entry.published
        )

        if date.tzinfo is None:
            date = date.replace(
                tzinfo=timezone.utc
            )

        return date

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "=== 🚀 크립토 최신 뉴스 봇 실행 ==="
    )

    try:

        # -------------------------------------------------
        # API KEY 확인
        # -------------------------------------------------

        if not GEMINI_API_KEY:
            print("❌ GEMINI_API_KEY 없음")
            return

        # -------------------------------------------------
        # 1. Google News 검색
        # -------------------------------------------------

        query = (
            "암호화폐 OR 비트코인 OR "
            "이더리움 OR 리플 OR XRP "
            "OR 솔라나 OR 코인"
        )

        keyword = urllib.parse.quote(query)

        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={keyword}"
            "&hl=ko"
            "&gl=KR"
            "&ceid=KR:ko"
        )

        print("🔎 Google News 확인 중...")

        response = requests.get(
            rss_url,
            headers=HEADERS,
            timeout=20
        )

        if response.status_code != 200:

            print(
                "❌ RSS 접근 실패:",
                response.status_code
            )

            return

        feed = feedparser.parse(
            response.content
        )

        if not feed.entries:

            print(
                "❌ 검색된 뉴스 없음"
            )

            return

        print(
            f"📰 검색 뉴스: "
            f"{len(feed.entries)}개"
        )

        # -------------------------------------------------
        # 2. 최신순 정렬
        # -------------------------------------------------

        entries = sorted(
            feed.entries,
            key=get_date,
            reverse=True
        )

        sent_urls = load_sent_urls()

        now = datetime.now(
            timezone.utc
        )

        target_entry = None
        target_link = None

        # -------------------------------------------------
        # 3. 최근 1시간 + 미전송 뉴스 찾기
        # -------------------------------------------------

        for entry in entries:

            published = get_date(entry)

            # 날짜 정보 없는 기사 제외
            if published.year == 1:
                continue

            age = now - published

            # 미래 날짜 오류 기사 제외
            if age.total_seconds() < 0:
                continue

            # 1시간 지난 뉴스 제외
            if age > timedelta(hours=1):
                continue

            # 실제 기사 링크 확인
            article_url = resolve_article_url(
                entry
            )

            # Google News 링크 / 실제 링크
            # 둘 중 하나라도 이미 전송했으면 제외
            if (
                article_url in sent_urls
                or entry.link in sent_urls
            ):
                continue

            target_entry = entry
            target_link = article_url

            break

        # -------------------------------------------------
        # 새 뉴스 없음
        # -------------------------------------------------

        if target_entry is None:

            print(
                "✅ 새로 보낼 최신 뉴스가 없습니다."
            )

            return

        # -------------------------------------------------
        # 선택 기사
        # -------------------------------------------------

        title = target_entry.title
        link = target_link

        print("")
        print("📰 선택 뉴스:")
        print(title)

        print("")
        print("🔗 기사 링크:")
        print(link)

        # -------------------------------------------------
        # 4. Gemini
        # -------------------------------------------------

        client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        prompt = f"""
너는 암호화폐 뉴스 전문 요약 에디터다.

아래 뉴스를 모바일 텔레그램에서
빠르게 읽을 수 있도록 짧고 정확하게 요약한다.

[중요 규칙]

- 인사말 없이 바로 뉴스 내용부터 시작한다.
- 본문은 짧은 2문단으로 작성한다.
- 각 문단은 너무 길게 작성하지 않는다.
- 모바일 화면에서 읽기 편하게 작성한다.
- 어려운 암호화폐 전문용어는 쉽게 설명한다.
- 불필요한 배경 설명은 제거한다.
- 같은 내용을 반복하지 않는다.
- 기사에 없는 사실을 만들어내지 않는다.
- 추측이나 투자 권유를 하지 않는다.
- 중요한 코인명, 기업명, 인물명, 수치는 유지한다.
- 과도한 이모티콘은 사용하지 않는다.

마지막에는 반드시 아래 형식을 사용한다.

📌 짧게 말씀드리면..
기사 전체의 핵심을 한 문장으로 요약한다.

중요:
기사 링크는 네가 만들거나 수정하지 않는다.
링크 문장은 시스템에서 별도로 추가한다.

[뉴스]

제목:
{title}
"""

        # -------------------------------------------------
        # Gemini 실행
        # -------------------------------------------------

        result = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt
        )

        if (
            not result
            or not result.text
        ):

            print(
                "❌ Gemini 응답 없음"
            )

            return

        # Gemini 본문
        text = result.text.strip()

        # -------------------------------------------------
        # 5. 링크는 코드에서 직접 추가
        # -------------------------------------------------

        text += (
            "\n\n"
            f"🔗 [기사 원문 보러가기]({link})"
        )

        print("")
        print("===== 최종 메시지 =====")
        print(text)
        print("=======================")

        # -------------------------------------------------
        # 6. Telegram 전송
        # -------------------------------------------------

        if send_telegram(text):

            print("")
            print("🎉 뉴스 전송 성공")

            # 실제 사용된 링크 저장
            save_sent_url(link)

            # Google News RSS 링크도 같이 저장
            # 실제 링크 추출 방식이 바뀌어도
            # 같은 기사가 다시 나가는 것을 방지
            if target_entry.link != link:
                save_sent_url(
                    target_entry.link
                )

        else:

            print(
                "❌ 뉴스 전송 실패"
            )

    except Exception:

        print("💥 오류 발생")

        traceback.print_exc()


# =========================================================
# 실행
# =========================================================

if __name__ == "__main__":
    main()
