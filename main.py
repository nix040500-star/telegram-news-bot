import os
import traceback
import requests
import feedparser
from google import genai
import urllib.parse

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ [텔레그램 에러] 토큰 또는 챗 ID가 설정되지 않았습니다.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"텔레그램 응답 코드: {res.status_code}")
        print(f"텔레그램 응답 내용: {res.text}")

        if res.status_code != 200:
            return False
        return True

    except Exception as e:
        print(f"❌ [텔레그램 에러] 예외 발생: {e}")
        return False


def main():
    print("=== 🚀 현시간 기준 크립토 실시간 뉴스 봇 실행 ===")

    try:
        if not GEMINI_API_KEY:
            print("❌ [에러] GEMINI_API_KEY가 설정되지 않았습니다.")
            return

        print("1. 구글 뉴스 RSS 현시간 기준 실시간 수집 중...")

        keyword = urllib.parse.quote("암호화폐")
        rss_url = (
            f"https://news.google.com/rss/search?"
            f"q={keyword}&hl=ko&gl=KR&ceid=KR:ko"
        )

        headers = {"User-Agent": "Mozilla/5.0"}
        response_rss = requests.get(
            rss_url,
            headers=headers,
            timeout=10
        )

        if response_rss.status_code != 200:
            print(
                f"❌ [에러] RSS 접근 실패 "
                f"(코드: {response_rss.status_code})"
            )
            return

        feed = feedparser.parse(response_rss.content)

        if not feed.entries:
            print("❌ [에러] 수집된 뉴스가 없습니다.")
            return

        target_entry = feed.entries[0]

        title = target_entry.title
        link = target_entry.link

        print(f"✨ 현시간 최신 뉴스 포착 완료: {title}")

        print("2. Gemini AI 전문 요약 생성 중...")

        client = genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""
너는 전문적인 크립토 시장 분석가이자 트렌디한 뉴스 채널 운영자야.
아래 제공되는 뉴스 기사를 분석하여 스마트폰에서 읽기 편하게 요약해줘.

[작성 포맷 및 규칙]

1. 서두나 인사말은 절대 작성하지 말고 바로 기사의 핵심 내용부터 시작할 것.

2. 기사의 배경, 시장 동향, 기술적 분석이나 향후 전망을 이해하기 쉽게
3~4문단의 자연스러운 본문으로 작성할 것.

3. 📌 "짧게 말씀드리면.."이라는 소제목 아래에
전체 내용을 1~2줄로 압축한 핵심 요약을 작성할 것.

4. 마지막 줄에는 반드시 아래 링크를 포함할 것.

🔗 [기사 원문 보러가기]({link})

[대상 기사]

제목: {title}

링크: {link}
"""

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
        )

        if response and response.text:

            result_text = response.text

            if (
                "[기사 원문 보러가기]" not in result_text
                and "🔗" not in result_text
            ):
                result_text += (
                    f"\n\n🔗 [기사 원문 보러가기]({link})"
                )

            print("3. 텔레그램 전송 시도...")

            success = send_telegram(result_text)

            if success:
                print("🎉 현시간 뉴스 전송 성공!")
            else:
                print("❌ 텔레그램 전송 실패")

        else:
            print(
                "❌ [에러] Gemini AI로부터 "
                "응답을 받지 못했습니다."
            )

    except Exception:
        print("💥 [치명적 예외 발생]")
        traceback.print_exc()


if __name__ == "__main__":
    main()
