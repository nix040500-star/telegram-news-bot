import os
import re
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
# 중복 기록 불러오기
# =========================================================

def load_sent_items():

    if not os.path.exists(SENT_FILE):
        return set()

    try:

        with open(
            SENT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return {
                line.strip()
                for line in f
                if line.strip()
            }

    except Exception as e:

        print(
            "⚠️ 전송 기록 읽기 실패:",
            e
        )

        return set()


# =========================================================
# 중복 기록 저장
# =========================================================

def save_sent_item(item):

    if not item:
        return

    item = item.strip()

    if not item:
        return

    with open(
        SENT_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            item + "\n"
        )


# =========================================================
# 기사 제목 정규화
#
# 같은 제목인데 공백/특수문자/대소문자 차이 때문에
# 중복으로 인식하지 못하는 문제 방지
# =========================================================

def normalize_title(title):

    if not title:
        return ""

    title = title.lower()

    # Google News 제목 뒤 언론사 제거를 어느 정도 보조
    title = re.sub(
        r"\s+",
        " ",
        title
    )

    # 한글 / 영문 / 숫자만 남김
    title = re.sub(
        r"[^가-힣a-z0-9]",
        "",
        title
    )

    return title.strip()


# =========================================================
# 제목 중복 확인용 KEY 생성
# =========================================================

def make_title_key(title):

    normalized = normalize_title(
        title
    )

    if not normalized:
        return ""

    return (
        "TITLE:"
        + normalized
    )


# =========================================================
# Google News → 실제 기사 URL 확인
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

        if (
            final_url
            and final_url.startswith("http")
            and "news.google.com"
            not in final_url
        ):

            return final_url

    except Exception as e:

        print(
            "⚠️ 실제 기사 URL 확인 실패:",
            e
        )

    # 실패하면 Google News 해당 기사 주소 사용
    return google_link


# =========================================================
# 뉴스 발행시간
# =========================================================

def get_date(entry):

    try:

        date = (
            email.utils
            .parsedate_to_datetime(
                entry.published
            )
        )

        if date.tzinfo is None:

            date = date.replace(
                tzinfo=timezone.utc
            )

        return date.astimezone(
            timezone.utc
        )

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


# =========================================================
# Gemini가 혹시 링크를 만들어도 제거
# =========================================================

def clean_gemini_text(text):

    if not text:
        return ""

    text = text.strip()

    # Gemini가 기사 링크를 임의로 생성한 경우 제거
    text = re.sub(
        r"\n*🔗\s*"
        r"\[기사 원문 보러가기\]"
        r"\([^)]+\)",
        "",
        text
    )

    return text.strip()


# =========================================================
# Telegram 전송
# =========================================================

def send_telegram(text):

    if not TELEGRAM_TOKEN:

        print(
            "❌ TELEGRAM_TOKEN 없음"
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID 없음"
        )

        return False

    telegram_url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/"
        "sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:

        response = requests.post(
            telegram_url,
            json=payload,
            timeout=30
        )

        print(
            "📡 Telegram 응답:",
            response.status_code
        )

        if response.status_code != 200:

            print(
                "❌ Telegram 오류:"
            )

            print(
                response.text
            )

            return False

        return True

    except Exception as e:

        print(
            "❌ Telegram 요청 오류:",
            e
        )

        return False


# =========================================================
# MAIN
# =========================================================

def main():

    print("")
    print(
        "======================================"
    )
    print(
        "🚀 크립토 최신 뉴스 봇 실행"
    )
    print(
        "======================================"
    )

    try:

        # =================================================
        # 환경변수 확인
        # =================================================

        if not GEMINI_API_KEY:

            print(
                "❌ GEMINI_API_KEY 없음"
            )

            return

        if not TELEGRAM_TOKEN:

            print(
                "❌ TELEGRAM_TOKEN 없음"
            )

            return

        if not TELEGRAM_CHAT_ID:

            print(
                "❌ TELEGRAM_CHAT_ID 없음"
            )

            return


        # =================================================
        # 1. Google News 검색
        # =================================================

        query = (
            "코인 OR 암호화폐 OR 가상자산 OR "
            "비트코인 OR BTC OR 이더리움 OR ETH OR "
            "리플 OR XRP OR 도지코인 OR 도지 OR DOGE OR "
            "스테이블코인 OR USDT OR ETF OR SEC OR "
            "연준 OR Fed OR FOMC OR 연준 의장 OR 금리 OR 파월"
        )

        keyword = urllib.parse.quote(
            query
        )

        rss_url = (
            "https://news.google.com/"
            "rss/search?"
            f"q={keyword}"
            "&hl=ko"
            "&gl=KR"
            "&ceid=KR:ko"
        )

        print("")
        print(
            "🔎 Google News 확인 중..."
        )

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
                "❌ 검색된 뉴스가 없습니다."
            )

            return

        print(
            f"📰 검색 결과: "
            f"{len(feed.entries)}개"
        )


        # =================================================
        # 2. 최신순 정렬
        # =================================================

        entries = sorted(
            feed.entries,
            key=get_date,
            reverse=True
        )

        sent_items = load_sent_items()

        print(
            f"📚 기존 중복 기록: "
            f"{len(sent_items)}개"
        )

        now = datetime.now(
            timezone.utc
        )


        # =================================================
        # 3. 새 기사 전부 찾기
        # =================================================

        new_entries = []

        # 이번 실행 중 발견한 제목도 따로 관리
        current_titles = set()

        for entry in entries:

            published = get_date(
                entry
            )

            # 날짜 없는 기사 제외
            if published.year == 1:
                continue

            age = (
                now - published
            )

            # 미래 시간 오류 제외
            if age.total_seconds() < 0:
                continue

            # -------------------------------------------------
            # 최근 6시간 기사만 확인
            #
            # 5분마다 실행되더라도
            # GitHub Actions 지연/실패가 발생했을 때
            # 놓친 뉴스를 다시 잡기 위한 안전 범위
            # -------------------------------------------------

            if age > timedelta(
                hours=6
            ):
                continue


            google_url = entry.link

            title_key = make_title_key(
                entry.title
            )


            # =================================================
            # 중복 검사 1
            # Google News URL
            # =================================================

            if google_url in sent_items:

                print(
                    "⏭️ Google URL 중복:",
                    entry.title
                )

                continue


            # =================================================
            # 중복 검사 2
            # 제목
            # =================================================

            if (
                title_key
                and title_key in sent_items
            ):

                print(
                    "⏭️ 제목 중복:",
                    entry.title
                )

                continue


            # =================================================
            # 중복 검사 3
            # 이번 실행에서 이미 발견한 제목
            # =================================================

            if (
                title_key
                and title_key in current_titles
            ):

                print(
                    "⏭️ 실행 내 제목 중복:",
                    entry.title
                )

                continue


            # =================================================
            # 실제 기사 URL 확인
            # =================================================

            article_url = (
                resolve_article_url(
                    entry
                )
            )


            # =================================================
            # 중복 검사 4
            # 실제 기사 URL
            # =================================================

            if article_url in sent_items:

                print(
                    "⏭️ 실제 URL 중복:",
                    entry.title
                )

                continue


            # =================================================
            # 새 기사 등록
            # =================================================

            new_entries.append(
                {
                    "entry": entry,
                    "link": article_url,
                    "published": published,
                    "title_key": title_key
                }
            )

            if title_key:

                current_titles.add(
                    title_key
                )


        # =================================================
        # 새 뉴스 없음
        # =================================================

        if not new_entries:

            print("")
            print(
                "✅ 새로 보낼 코인 뉴스가 없습니다."
            )

            return


        print("")
        print(
            f"🔥 새 뉴스 "
            f"{len(new_entries)}개 발견"
        )


        # =================================================
        # 오래된 기사부터 순서대로 전송
        # =================================================

        new_entries.sort(
            key=lambda x:
            x["published"]
        )


        # =================================================
        # Gemini 준비
        # =================================================

        client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        success_count = 0
        fail_count = 0


        # =================================================
        # 4. 모든 새 기사 처리
        # =================================================

        for index, item in enumerate(
            new_entries,
            start=1
        ):

            target_entry = (
                item["entry"]
            )

            title = (
                target_entry.title
            )

            link = (
                item["link"]
            )

            published = (
                item["published"]
            )

            title_key = (
                item["title_key"]
            )

            print("")
            print(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )

            print(
                f"📰 {index}/"
                f"{len(new_entries)} 처리"
            )

            print(
                "제목:",
                title
            )

            print(
                "발행:",
                published.isoformat()
            )

            print(
                "링크:",
                link
            )


            # =================================================
            # Gemini 프롬프트
            # =================================================

            prompt = f"""
너는 암호화폐 뉴스 전문 요약 에디터다.

아래 뉴스를 모바일 텔레그램에서
빠르게 읽을 수 있도록 짧고 정확하게 요약한다.

[작성 규칙]

- 인사말 없이 바로 뉴스 내용부터 시작한다.
- 본문은 짧은 2문단으로 작성한다.
- 각 문단은 너무 길게 작성하지 않는다.
- 모바일 화면에서 읽기 편하게 작성한다.
- 어려운 암호화폐 전문용어는 쉽게 설명한다.
- 불필요한 배경 설명은 제거한다.
- 같은 내용을 반복하지 않는다.
- 기사 제목에서 확인할 수 없는 사실은 임의로 만들지 않는다.
- 추측하지 않는다.
- 투자 권유를 하지 않는다.
- 중요한 코인명, 기업명, 인물명, 수치는 유지한다.
- 과도한 이모티콘은 사용하지 않는다.

마지막에는 반드시 아래 형식으로 작성한다.

📌 짧게 말씀드리면..
기사 전체 핵심을 한 문장으로 요약한다.

[매우 중요]

기사 URL은 절대로 작성하지 않는다.
기사 URL을 추측하지 않는다.
'기사 원문 보러가기' 문구를 작성하지 않는다.
링크는 Python 프로그램이 별도로 추가한다.

[뉴스 제목]

{title}
"""


            # =================================================
            # Gemini 실행
            # =================================================

            try:

                print(
                    "🤖 Gemini 요약 생성 중..."
                )

                result = (
                    client.models
                    .generate_content(
                        model="gemini-3.6-flash",
                        contents=prompt
                    )
                )


                if (
                    not result
                    or not result.text
                ):

                    print(
                        "❌ Gemini 응답 없음"
                    )

                    fail_count += 1

                    continue


                text = clean_gemini_text(
                    result.text
                )


                if not text:

                    print(
                        "❌ Gemini 요약 없음"
                    )

                    fail_count += 1

                    continue


                # =================================================
                # 정확한 기사 URL 직접 추가
                # =================================================

                text += (
                    "\n\n"
                    f"🔗 [기사 원문 보러가기]"
                    f"({link})"
                )


                # =================================================
                # Telegram 전송
                # =================================================

                if not send_telegram(
                    text
                ):

                    print(
                        "❌ Telegram 전송 실패"
                    )

                    fail_count += 1

                    # 실패한 뉴스는 저장하지 않음
                    # 다음 실행에서 다시 시도
                    continue


                # =================================================
                # 전송 성공
                # =================================================

                print(
                    "✅ Telegram 전송 성공"
                )

                success_count += 1


                # =================================================
                # 5. 중복 기록 저장
                # =================================================

                # 실제 기사 URL
                save_sent_item(
                    link
                )

                sent_items.add(
                    link
                )


                # Google News URL
                if target_entry.link:

                    save_sent_item(
                        target_entry.link
                    )

                    sent_items.add(
                        target_entry.link
                    )


                # 정규화 제목
                if title_key:

                    save_sent_item(
                        title_key
                    )

                    sent_items.add(
                        title_key
                    )


                print(
                    "💾 중복 방지 기록 완료"
                )


            except Exception as e:

                print(
                    "❌ 기사 처리 중 오류:",
                    e
                )

                traceback.print_exc()

                fail_count += 1

                # 한 기사 실패해도
                # 나머지 기사 계속 처리
                continue


        # =================================================
        # 최종 결과
        # =================================================

        print("")
        print(
            "======================================"
        )

        print(
            "🏁 이번 뉴스 확인 완료"
        )

        print(
            f"✅ 전송 성공: "
            f"{success_count}개"
        )

        print(
            f"❌ 전송 실패: "
            f"{fail_count}개"
        )

        print(
            "======================================"
        )


    except Exception:

        print("")
        print(
            "💥 프로그램 실행 오류"
        )

        traceback.print_exc()


# =========================================================
# 실행
# =========================================================

if __name__ == "__main__":
    main()
