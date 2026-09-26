import os
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

IMAGES = [
    "지갑보안검사 메뉴얼.png",
    "트론충전 메뉴얼.png"
]

url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

for image in IMAGES:
    with open(image, "rb") as f:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID},
            files={"photo": f},
            timeout=60
        )

    if response.status_code != 200:
        raise Exception(f"{image} 전송 실패: {response.text}")

    print(f"{image} 전송 완료")
