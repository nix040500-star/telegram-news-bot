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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("🚨 [디버깅] 에러: TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다!")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    
    try:
        res = requests.post(url, json=payload)
        print(f"텔레그램 전송 응답 코드: {res.status_code}")
        print(f"텔레그램 응답 본문: {res.text}")
        if res.status_code != 200:
            return False
        return True
    except Exception as e:
        print(f"🚨 [디버깅] 텔레그램 요청 중 예외 발생: {e}")
        return False

def main():
    print("--- 🚀 크립토 실시간 뉴스 봇 실행 시작 ---")
    
    if not GEMINI_API_KEY:
        print("🚨 [디버깅] 에러: GEMINI_API_KEY가 설정되지 않았습니다!")
        return

    print("1. 구글 뉴스 RSS 수집 시도 중...")
    keyword = urllib.parse.quote("암호화폐")
    rss_url = f"https://news.google.com/rss/search?q={keyword}&hl=ko&gl=KR&ceid=KR:ko"
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    response_rss = requests.get(rss_url, headers=headers)
    
    print(f"RSS 응답 상태 코드: {response_rss.status_code}")
    
    if response_rss.status_code != 200:
        print(f"🚨 [디버깅] RSS 접근 실패! 코드: {response_rss.status_code}")
        return

    feed = feedparser.parse(response_rss.content)
    print(f"수집된 전체 기사 개수: {len(feed.entries)}")
    
    if not feed.entries:
        print("🚨 [디버깅] 경고: RSS 피드에 가져온 뉴스가 아예 없습니다!")
        return

    target_entry = feed.entries[0]
    title = target_entry.title
    link = target_entry.link
    
    print(f"✨ 최신 뉴스 포착 성공 -> 제목: {title}")
    print(f"🔗 링크: {link}")

    print("2. Gemini AI 스마트폰 맞춤형 압축 요약 생성 중...")
    genai.configure(api_key=GEMINI_API_KEY)
    
    prompt = f"""
너는 트렌디한 크립토 채널 운영자야. 아래 뉴스를 스마트폰 푸시 알림이나 화면으로 볼 때 **스크롤 없이 한눈에 쏙 들어오도록 아주 짧고 강렬하게** 요약해줘.

[엄격한 작성 규칙]
1. 인사말이나 서두 멘트 절대 금지. 곧바로 핵심 내용부터 시작할 것.
2. 장황한 설명 대신 핵심 팩트만 **딱 2~3줄 이내**로 극단적으로 압축할 것.
3. 내용과 어울리는 이모티콘을 **딱 1~2개만** 센스 있게 사용할 것.
4. 마지막 줄에 반드시 아래 링크 형식을 포함할 것:
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
        
        print("3. 텔레그램 전송 시도 중...")
        success = send_telegram(result_text)
        if success:
            print("🎉 모든 작업 성공적으로 완료!")
        else:
            print("🚨 [디버깅] 텔레그램 전송이 거부되었거나 실패했습니다.")
    else:
        print("🚨 [디버깅] Gemini AI로부터 텍스트 응답을 받지 못했습니다.")

if __name__ == "__main__":
    main()
