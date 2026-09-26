import os
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

API_URL = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

# 지갑보안검사 이미지 + 멘트
caption = """*USDT 스캔 가드(USDT SCAN GUARD)*

빠르고 안전한 디지털 자산 보안 관리

• *보안 점검:* 자산 및 주소 안전성 실시간 확인
• *위험 차단:* 잠재적 위협 요소 사전 예방
• *체계적 보호:* 믿을 수 있는 디지털 자산 관리

지갑의 위험을 미리 확인하고, 더 안전하게 보호하세요.

[바로 검사하기](https://hig.kr/usdt-security)"""

with open("지갑보안검사 메뉴얼.png", "rb") as image:
    response = requests.post(
        API_URL,
        data={
            "chat_id": CHAT_ID,
            "caption": caption,
            "parse_mode": "Markdown"
        },
        files={"photo": image},
        timeout=60
    )

if response.status_code != 200:
    raise Exception(f"지갑보안검사 전송 실패: {response.text}")

print("지갑보안검사 전송 완료")


# 트론충전 메뉴얼은 이미지만 전송
with open("트론충전 메뉴얼.png", "rb") as image:
    response = requests.post(
        API_URL,
        data={"chat_id": CHAT_ID},
        files={"photo": image},
        timeout=60
    )

if response.status_code != 200:
    raise Exception(f"트론충전 메뉴얼 전송 실패: {response.text}")

print("트론충전 메뉴얼 전송 완료")
