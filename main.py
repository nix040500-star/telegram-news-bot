import os
import re
import hashlib
import random
import traceback
import requests
import feedparser
import urllib.parse
import email.utils
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from google import genai


# =========================================================
# 환경변수
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SENT_FILE = "sent_urls.txt"

# 최근 1시간 이내 기사만 허용
MAX_ARTICLE_AGE_HOURS = 1

# 한 번 실행할 때 뉴스는 최대 1개만 전송
MAX_ARTICLES_PER_RUN = 1


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
    "crypto", "cryptocurrency", "bitcoin", "btc",
    "ethereum", "eth", "xrp", "ripple",
    "dogecoin", "doge", "stablecoin", "usdt",
    "tether", "coinbase", "binance", "blockchain",
    "digital asset", "token",
    "코인", "암호화폐", "가상자산",
    "비트코인", "이더리움", "리플",
    "도지코인", "도지", "스테이블코인"
]


MACRO_TERMS = [
    "federal reserve", "fed", "fomc",
    "powell", "interest rate",
    "rate hike", "rate cut",
    "inflation", "sec", "etf",
    "연준", "파월", "금리", "인플레이션"
]


GOOGLE_QUERY = (
    '("코인" OR "암호화폐" OR "가상자산" OR '
    '"비트코인" OR BTC OR '
    '"이더리움" OR ETH OR '
    '"리플" OR XRP OR '
    '"도지코인" OR DOGE OR '
    '"스테이블코인" OR USDT OR '
    'ETF OR SEC OR "연준" OR Fed OR '
    'FOMC OR "연준 의장" OR "금리" OR "파월") when:1d'
)


google_rss = (
    "https://news.google.com/rss/search?"
    f"q={urllib.parse.quote(GOOGLE_QUERY)}"
    "&hl=ko&gl=KR&ceid=KR:ko"
)


FEEDS = [
    ("Google News KR", google_rss, "google"),
    (
        "Federal Reserve - Monetary Policy",
        "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "macro"
    ),
    (
        "Federal Reserve - Speeches",
        "https://www.federalreserve.gov/feeds/speeches.xml",
        "macro"
    ),
