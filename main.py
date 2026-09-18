import os
import traceback
import requests
import feedparser
import google.generativeai as genai
import urllib.parse

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    res = requests.post(url, json=payload)
    print(f"텔레그램 응답 코드: {res.status_code}")
    print(f"텔레그램 응답 내용: {res.text}")
    return res.status_code == 200

def main():
    try:
        print("=== 크립토 뉴스 봇 디버깅 시작 ===")
        
        if not TELEGRAM_TOKEN:
            print("❌ 에러: TELEGRAM_TOKEN 비밀값이 설정되지 않았습니다.")
        if not TELEGRAM_CHAT_ID:
            print("❌ 에러: TELEGRAM_CHAT_ID 비밀값이 설정되지 않았습니다.")
        if not GEMINI_API_KEY:
            print("❌ 에러: GEMINI_API_KEY 비밀값이 설정되지 않았습니다.")

        print("1. 구글 뉴스 RSS 수집 시도...")
        keyword = urllib.parse.quote("암호화폐")
        rss_url = f"https://news.google.com/rss/search?q={keyword}&hl=ko&gl=KR&ceid=KR:ko"
        
        headers = {"User-Agent": "Mozilla/5.0"}
        response_rss = requests.get(rss_url, headers=headers)
        print(f"RSS 요청 응답 코드: {response_rss.status_code}")
        
        feed = feedparser.parse(response_rss.content)
        print(f"수집된 기사 수: {len(feed.entries)}")
        
        if not feed.entries:
            print("❌ 에러: 수집된 뉴스가 없습니다.")
            return

        target_entry = feed.entries[0]
        title = target_entry.title
        link = target_entry.link
        print(f"포착된 뉴스 제목: {title}")

        print("2. Gemini AI 요약 생성 시도...")
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
너는 트렌디한 크립토 채널 운영자야. 아래 뉴스를 스마트폰 화면에 스크롤 없이 한눈에 들어오도록 2~3줄로 압축 요약해줘.
인사말이나 서두 없이 곧바로 본문부터 시작하고, 마지막 줄에 원문 링크를 넣어줘.

제목: {title}
링크: {link}
"""
        response = model.generate_content(prompt)
        if not response or not response.text:
            print("❌ 에러: Gemini AI가 빈 응답을 반환했습니다.")
            return

        result_text = response.text
        if "[기사 원문 보러가기]" not in result_text and "🔗" not in result_text:
            result_text += f"\n\n🔗 [기사 원문 보러가기]({link})"

        print("3. 텔레그램 전송 시도...")
        success = send_telegram(result_text)
        if success:
            print("🎉 모든 작업 성공!")
        else:
            print("❌ 에러: 텔레그램 전송 실패.")

    except Exception as e:
        print("💥 치명적인 예외(Exception) 발생!")
        traceback.print_exc()
        raise e

if __name__ == "__main__":
    main()
