import os
import feedparser
import requests
import google.generativeai as genai

# 환경 변수 불러오기 (GitHub Secrets에서 가져옴)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# AI 설정 (Gemini)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# 구글 뉴스 암호화폐 RSS URL (최신순)
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q=%EC%95%94%ED%98%B8%ED%99%94%ED%8F%90+OR+%EB%B9%84%ED%8A%B8%EC%BD%94%EC%9D%B8&hl=ko&gl=KR&ceid=KR:ko"

# [핵심 프롬프트 템플릿]
NEWS_PROMPT_TEMPLATE = """
너는 전문 크립토(암호화폐) 뉴스 에디터야. 
아래 제공되는 구글 뉴스 기사 원문을 바탕으로, 텔레그램 채널에 바로 게시할 수 있도록 핵심만 요약해 줘.

[작성 규칙]
1. 톤앤매너: 객관적이되, 투자자들이 한눈에 파악하기 쉽게 트렌디하고 직관적인 어조 사용
2. 분량: 30초 만에 읽을 수 있도록 핵심 위주로 압축 (공백 포함 300자 이내)
3. 필수 포함 내용:
   - 📌 [제목]: 독자의 이목을끄는 직관적인 한 줄 제목 (이모지 포함)
   - 🔍 [핵심 요약]: 사건의 배경과 내용을 2~3줄의 불렛 포인트(*)로 정리
   - 💡 [시장 영향/시사점]: 해당 뉴스가 코인 시장에 미치는 영향 한 줄 평
   - 🔗 [출처]: 제공된 링크 유지
4. 가독성: 텔레그램 마크다운 형식을 활용해 가독성 극대화

[기사 제목 및 링크]
제목: {title}
링크: {link}

[기사 본문 요약/내용]
{summary}
"""

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    return response.json()

def main():
    # RSS 피드 읽기
    feed = feedparser.parse(GOOGLE_NEWS_RSS)
    
    if not feed.entries:
        print("수집된 뉴스가 없습니다.")
        return

    # 가장 최신 뉴스 1개만 가져오기 (실시간 봇용)
    latest_entry = feed.entries[0]
    
    title = latest_entry.get("title", "")
    link = latest_entry.get("link", "")
    summary = latest_entry.get("summary", title)

    print(f"새 뉴스 감지: {title}")

    # 프롬프트 조합
    prompt = NEWS_PROMPT_TEMPLATE.format(
        title=title,
        link=link,
        summary=summary
    )

    # Gemini AI에 요약 요청
    try:
        response = model.generate_content(prompt)
        ai_message = response.text
    except Exception as e:
        print(f"AI 요약 실패: {e}")
        return

    # 텔레그램 전송
    result = send_to_telegram(ai_message)
    if result.get("ok"):
        print("텔레그램 전송 성공!")
    else:
        print(f"텔레그램 전송 실패: {result}")

if __name__ == "__main__":
    main()
