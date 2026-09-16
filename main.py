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
        return {line.strip() for line in f if line.strip()}


def save_sent_url(url):
    with open(SENT_URLS_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def send_telegram(text):
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN이 설정되지 않았습니다.")

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID가 설정되지 않았습니다.")

    api_url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }

    response = requests.post(
        api_url,
        json=payload,
        timeout=30
    )

    if not response.ok:
        raise RuntimeError(
            "텔레그램 전송 실패: "
            + str(response.status_code)
            + " / "
            + response.text
        )

    print("텔레그램 전송 성공")


def main():
    print("뉴스봇 시작")

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

    rss_url = (
        "https://news.google.com/rss/search?"
        "q=비트코인+OR+암호화폐+OR+미국증시+OR+나스닥+OR+리플"
        "&hl=ko&gl=KR&ceid=KR:ko"
    )

    rss_response = requests.get(
        rss_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30
    )
    rss_response.raise_for_status()

    feed = feedparser.parse(rss_response.content)

    print("수집 기사:", len(feed.entries))

    if not feed.entries:
        print("수집된 뉴스가 없습니다.")
        return

    sent_urls = load_sent_urls()

    target_entry = None

    for entry in feed.entries:
        if entry.link not in sent_urls:
            target_entry = entry
            break

    if target_entry is None:
        print("새로운 기사가 없습니다.")
        return

    title = target_entry.title
    link = target_entry.link

    print("새 뉴스:", title)

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
아래 금융·암호화폐 뉴스를 한국어로 요약해줘.

작성 규칙:
- 객관적이고 신뢰감 있는 뉴스 스타일
- 핵심 내용을 3~4개의 자연스러운 단락으로 작성
- 불필요한 번호 매기기 금지
- 투자자가 이해하기 쉽게 작성
- 마지막 줄에 기사 링크 표시

제목:
{title}

기사 링크:
{link}
"""

    ai_response = None

    for attempt in range(3):
        try:
            print(f"Gemini 요약 시도 {attempt + 1}/3")

            ai_response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            break

        except ServerError:
            if attempt == 2:
                raise

            time.sleep(5)

    if ai_response is None or not ai_response.text:
        raise RuntimeError("Gemini 요약 결과가 없습니다.")

    result_text = ai_response.text.strip()

    result_text += (
        "\n\n🔗 기사 원문 보러가기\n"
        + link
    )

    print("Gemini 요약 완료")

    send_telegram(result_text)

    # 텔레그램 전송에 성공한 기사만 기록
    save_sent_url(link)

    print("기사 기록 완료")
    print("뉴스봇 정상 종료")


if __name__ == "__main__":
    main()
