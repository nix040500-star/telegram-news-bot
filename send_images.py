
import os
import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

IMAGES = [
    {
        "file": "지갑보안검사 메뉴얼.png",
        "caption": """USDT 스캔 가드(USDT SCAN GUARD)

빠르고 안전한 디지털 자산 보안 관리

• 보안 점검: 자산 및 주소 안전성 실시간 확인
• 위험 차단: 잠재적 위협 요소 사전 예방
• 체계적 보호: 믿을 수 있는 디지털 자산 관리

지갑의 위험을 미리 확인하고, 더 안전하게 보호하세요.

https://hig.kr/usdt-security"""
    },
    {
        "file": "트론충전 메뉴얼.png",
        "caption": """TRON (트론) 충전 가이드

빠르고 저렴한 글로벌 블록체인 네트워크

이미지를 참고하여 순서대로 진행해 주세요."""
    }
]

# 실행될 때마다 이미지 1장만 선택
# GitHub Actions에서 IMAGE_INDEX를 0 또는 1로 지정 가능
index = int(os.environ.get("IMAGE_INDEX", "0"))
item = IMAGES[index % len(IMAGES)]

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

with open(item["file"], "rb") as photo:
    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "caption": item["caption"]
        },
        files={"photo": photo},
        timeout=30
    )

response.raise_for_status()

print(f"전송 완료: {item['file']}")
