import os
import glob
import requests

BOT_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# 이미지 파일 자동 검색
def find_image(keyword):
    files = glob.glob("*.png") + glob.glob("*.jpg") + glob.glob("*.jpeg")
    for file in files:
        if keyword in file:
            return file
    raise FileNotFoundError(
        f"'{keyword}' 이미지 파일을 찾을 수 없습니다. 현재 파일: {files}"
    )

wallet_image = find_image("지갑보안검사")
tron_image = find_image("트론충전")

IMAGES = [
    {
        "file": wallet_image,
        "caption": """USDT 스캔 가드(USDT SCAN GUARD)

빠르고 안전한 디지털 자산 보안 관리

• 보안 점검: 자산 및 주소 안전성 실시간 확인
• 위험 차단: 잠재적 위협 요소 사전 예방
• 체계적 보호: 믿을 수 있는 디지털 자산 관리

지갑의 위험을 미리 확인하고, 더 안전하게 보호하세요.

https://hig.kr/usdt-security"""
    },
    {
        "file": tron_image,
        "caption": """TRON (트론) 충전 가이드

빠르고 저렴한 글로벌 블록체인 네트워크

이미지를 참고하여 순서대로 진행해 주세요."""
    }
]

# 실행 시간(KST/JST)에 따라 이미지 선택
# 00시, 12시 = 지갑보안검사
# 06시, 18시 = 트론충전
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
hour = datetime.now(KST).hour

if hour in [0, 12]:
    index = 0
elif hour in [6, 18]:
    index = 1
else:
    # 수동 테스트 실행 시 첫 번째 이미지 전송
    index = 0

item = IMAGES[index]

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

with open(item["file"], "rb") as photo:
    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "caption": item["caption"],
            "parse_mode": "HTML"
        },
        files={
            "photo": photo
        },
        timeout=30
    )

if not response.ok:
    print("Telegram 오류:", response.text)
    response.raise_for_status()

print("전송 성공:", item["file"])
