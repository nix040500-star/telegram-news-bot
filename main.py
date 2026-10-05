import os
import re
import html
import time
import random
import hashlib
import requests
import feedparser
import urllib.parse
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from google import genai


# =========================================================
# 환경변수
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN 환경변수가 없습니다.")

if not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_CHAT_ID 환경변수가 없습니다.")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY 환경변수가 없습니다.")


# =========================================================
# 핵심 설정
# =========================================================

SENT_FILE = "sent_urls.txt"

# 최근 2시간 기사만 후보
# GitHub Actions 지연이나 RSS 발행 지연을 감안한 여유값
MAX_ARTICLE_AGE_HOURS = 2

# ★ 한 번 실행할 때 최대 2개
MAX_ARTICLES_PER_RUN = 2

# 제목이 이 정도 이상 비슷하면 같은 뉴스로 판단
TITLE_SIMILARITY = 0.86

# 기록 파일 최대 보관 개수
MAX_SENT_HISTORY = 5000

KST = timezone(timedelta(hours=9))


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    )
}


# =========================================================
# 뉴스 키워드
# =========================================================

CRYPTO_TERMS = [
    "crypto",
    "cryptocurrency",
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "xrp",
    "ripple",
    "dogecoin",
    "doge",
    "solana",
    "sol",
    "stablecoin",
    "usdt",
    "usdc",
    "tether",
    "coinbase",
    "binance",
    "blockchain",
    "digital asset",

    "코인",
    "암호화폐",
    "가상자산",
    "비트코인",
    "이더리움",
    "리플",
    "도지코인",
