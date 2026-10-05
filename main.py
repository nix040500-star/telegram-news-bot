import os
import re
import html
import hashlib
import urllib.parse
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

import feedparser
import requests
from google import genai


# =========================================================
# 환경변수
# =========================================================

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

KST = timezone(timedelta(hours=9))

SENT_FILE = "sent_urls.txt"

# 최대 6시간 이내 기사
# 뉴스가 부족해서 아무것도 안 올라오는 문제를 줄이기 위해
# 기존 2시간보다 넉넉하게 잡음
MAX_ARTICLE_AGE_HOURS = 6

# 실행 1회당 무조건 최대 1개
MAX_ARTICLES_PER_RUN = 1

# 유사 제목 중복 기준
TITLE_SIMILARITY = 0.76

# 중복 기록 최대 보관량
MAX_SENT_HISTORY = 10000


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}


# =========================================================
# 검색 키워드
# =========================================================

CRYPTO_TERMS = [
    "crypto", "cryptocurrency", "bitcoin", "btc",
    "ethereum", "eth", "xrp", "ripple",
    "solana", "sol", "dogecoin", "doge",
    "stablecoin", "usdt", "usdc", "tether",
    "coinbase", "binance", "blockchain",
    "digital asset",

    "코인", "암호화폐", "가상자산",
    "비트코인", "이더리움", "리플",
    "솔라나", "도지코인",
    "스테이블코인", "테더",
]


STOCK_TERMS = [
    "nasdaq", "s&p 500", "s&p500", "dow",
    "wall street", "stock market",
    "stocks", "equities",
    "nvidia", "nvda",
    "tesla", "tsla",
    "apple", "aapl",
    "microsoft", "msft",
    "amazon", "amzn",
    "meta", "google", "alphabet",
    "amd", "broadcom",

    "나스닥", "다우", "미국 증시",
    "미국증시", "뉴욕증시",
    "엔비디아", "테슬라",
    "애플", "마이크로소프트",
    "아마존", "메타",
]


MACRO_TERMS = [
    "federal reserve", "fed", "fomc",
    "powell", "interest rate",
    "rate cut", "rate hike",
    "inflation", "cpi", "ppi",
    "jobs report", "payroll",
    "unemployment",
