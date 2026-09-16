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
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN이 없습니다.")
        return False

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID가 없습니다.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        if response.ok:
            print("✅ 텔레그램 전송 성공")
            return True

        print("❌ 텔레그램 전송 실패")
        print("상태 코드:", response.status_code)
        print("텔레그램 응답:", response.text)
        return False

    except Exception as e:
        print("❌ 텔레그램 연결 오류:", str(e))
        return False


def main():

    print("========== 뉴스봇 시작 ==========")

    # 환경변수 확인
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY가 없습니다.")
        return

    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN이 없습니다.")
        return

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID가 없습니다.")
        return

    print("✅ 환경변수 확인 완료")

    # 구글 뉴스 RSS
    rss_url = (
        "https://news.google.com/rss/search?"
        "q=비트코인+OR+암호화폐+OR+미국증시+OR+나스닥+OR+리플"
        "&hl=ko&gl=KR&ceid=KR:ko"
    )

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response_rss = requests.get(
            rss_url,
            headers=headers,
            timeout=20
        )

        response_rss.raise_for_status()

    except Exception as e:
        print("❌ 뉴스 RSS 접속 실패:", str(e))
        return

    feed = feedparser.parse(response_rss.content)

    print(f"📰 RSS에서 찾은 기사 수: {len(feed.entries)}")

    if not feed.entries:
        print("❌ 수집된 뉴스가 없습니다.")
        return

    sent_urls = load_sent_urls()

    target_entry = None

    for entry in feed.entries:
        if entry.link not in sent_urls:
            target_entry = entry
            break

    if not target_entry:
        print("ℹ️ 새로운 기사가 없습니다.")
        return

    title = target_entry.title
    link = target_entry.link

    print("📰 새 뉴스 발견")
    print("제목:", title)
    print("링크:", link)

    # Gemini 실행
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print("❌ Gemini 초기화 실패:", str(e))
        return

    prompt = f"""
너는 전문적인 금융·크립토 애널리스트야.

아래 제공되는 뉴스 기사를 바탕으로 투자자들이 핵심 내용을
한눈에 파악할 수 있도록 3~4개의 단락으로 작성해줘.

[작성 규칙]

1. 객관적이고 신뢰감 있는 금융 뉴스 스타일로 작성할 것.
2. 시장에 미칠 수 있는 의미를 자연스럽게 설명할 것.
3. 번호 매기기나 기계적인 개조식은 사용하지 말 것.
4. 자연스러운 줄글 형태로 단락을 구분할 것.
5. 마지막에는 반드시 아래 링크를 넣을 것.

🔗 [기사 원문 보러가기]({link})

[대상 기사]

제목: {title}
링크: {link}
"""

    max_retries = 3
    ai_response = None

    for attempt in range(max_retries):

        try:
            print(
                f"🤖 Gemini 요약 시도 "
                f"{attempt + 1}/{max_retries}"
            )

            ai_response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
            )

            break

        except ServerError as e:

            print("⚠️ Gemini 서버 오류:", str(e))

            if attempt < max_retries - 1:
                time.sleep(5)

        except Exception as e:
            print("❌ Gemini 오류:", str(e))
            return

    if not ai_response:
        print("❌ Gemini 요약 생성 실패")
        return

    try:
        result_text = ai_response.text
    except Exception as e:
        print("❌ Gemini 응답 읽기 실패:", str(e))
        return

    if not result_text:
        print("❌ Gemini가 빈 내용을 반환했습니다.")
        return

    print("✅ Gemini 뉴스 요약 완료")

    if "[기사 원문 보러가기]" not in result_text:
        result_text += (
            f"\n\n🔗 [기사 원문 보러가기]({link})"
        )

    # 텔레그램 전송
    telegram_success = send_telegram(result_text)

    # 실제 전송에 성공한 경우에만 저장
    if telegram_success:
        save_sent_url(link)
        print("✅ 전송 기사 기록 완료")
    else:
        print("❌ 전송 실패 → 기사 기록하지 않음")

    print("========== 뉴스봇 종료 ==========")


if __name__ == "__main__":
    main()
