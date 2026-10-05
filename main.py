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
    "treasury yield",
    "sec", "etf",

    "연준", "파월", "금리",
    "금리인하", "금리 인하",
    "금리인상", "금리 인상",
    "인플레이션", "소비자물가",
    "고용", "실업률",
    "국채금리", "SEC", "ETF",
]


# =========================================================
# Google News RSS
# =========================================================

GOOGLE_CRYPTO_QUERY = (
    '("Bitcoin" OR BTC OR Ethereum OR ETH OR XRP OR Ripple OR '
    'Solana OR cryptocurrency OR crypto OR stablecoin OR '
    'Coinbase OR Binance OR '
    '"비트코인" OR "이더리움" OR "리플" OR "가상자산") when:1d'
)

GOOGLE_STOCK_QUERY = (
    '("Nasdaq" OR "S&P 500" OR "Dow Jones" OR "Wall Street" OR '
    'Nvidia OR Tesla OR Apple OR Microsoft OR Amazon OR Meta OR '
    '"미국 증시" OR "뉴욕증시" OR "나스닥" OR "엔비디아") when:1d'
)

GOOGLE_MACRO_QUERY = (
    '("Federal Reserve" OR Fed OR FOMC OR Powell OR CPI OR '
    'inflation OR "interest rate" OR Treasury OR '
    '"연준" OR "파월" OR "금리" OR "소비자물가") when:1d'
)


def google_rss(query, lang="en-US", country="US", ceid="US:en"):
    return (
        "https://news.google.com/rss/search?"
        f"q={urllib.parse.quote(query)}"
        f"&hl={lang}&gl={country}&ceid={ceid}"
    )


# =========================================================
# RSS 목록
# 반드시 (이름, URL, 종류) 3개로 통일
# =========================================================

FEEDS = [
    (
        "Google Crypto",
        google_rss(GOOGLE_CRYPTO_QUERY),
        "crypto",
    ),
    (
        "Google US Stocks",
        google_rss(GOOGLE_STOCK_QUERY),
        "stock",
    ),
    (
        "Google Macro",
        google_rss(GOOGLE_MACRO_QUERY),
        "macro",
    ),
    (
        "CoinDesk",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "crypto",
    ),
    (
        "Cointelegraph",
        "https://cointelegraph.com/rss",
        "crypto",
    ),
    (
        "The Block",
        "https://www.theblock.co/rss.xml",
        "crypto",
    ),
    (
        "Decrypt",
        "https://decrypt.co/feed",
        "crypto",
    ),
    (
        "Blockworks",
        "https://blockworks.co/feed",
        "crypto",
    ),
    (
        "CryptoSlate",
        "https://cryptoslate.com/feed/",
        "crypto",
    ),
    (
        "Federal Reserve",
        "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "macro",
    ),
    (
        "Federal Reserve Speeches",
        "https://www.federalreserve.gov/feeds/speeches.xml",
        "macro",
    ),
    (
        "Reuters Crypto",
        google_rss(
            'site:reuters.com '
            '(Bitcoin OR Ethereum OR crypto OR cryptocurrency OR Coinbase) '
            'when:1d'
        ),
        "crypto",
    ),
    (
        "Reuters Markets",
        google_rss(
            'site:reuters.com '
            '("Wall Street" OR Nasdaq OR "S&P 500" OR Nvidia OR Tesla '
            'OR "Federal Reserve") when:1d'
        ),
        "stock",
    ),
    (
        "CNBC Markets",
        google_rss(
            'site:cnbc.com '
            '(Nasdaq OR "S&P 500" OR stocks OR Nvidia OR Tesla '
            'OR "Federal Reserve") when:1d'
        ),
        "stock",
    ),
]


# =========================================================
# 기본 유틸
# =========================================================

def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", str(text))
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_title(title):
    title = clean_text(title).lower()

    # 언론사 이름이 제목 뒤에 붙은 경우 제거에 도움
    title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)

    title = re.sub(
        r"[^0-9a-zA-Z가-힣]+",
        " ",
        title,
    )

    return re.sub(r"\s+", " ", title).strip()


def title_similarity(a, b):
    a = normalize_title(a)
    b = normalize_title(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


STOP_WORDS = {
    "the", "a", "an", "and", "or", "to",
    "of", "in", "on", "for", "with", "as",
    "at", "by", "from", "is", "are", "was",
    "were", "be", "after", "amid", "over",
    "says", "say", "news", "report",
    "reports", "latest", "update", "today",

    "대한", "관련", "통해", "위해",
    "에서", "으로", "하고", "한다",
    "발표", "소식", "전망",
}


def event_tokens(title):
    title = normalize_title(title)

    return {
        word
        for word in title.split()
        if len(word) >= 2 and word not in STOP_WORDS
    }


def same_event_title(a, b):
    """
    서로 다른 언론사가 같은 사건을 다른 제목으로 쓴 경우 차단.
    기존 코드의 자기 자신 재호출 오류 제거.
    """

    if title_similarity(a, b) >= TITLE_SIMILARITY:
        return True

    ta = event_tokens(a)
    tb = event_tokens(b)

    if not ta or not tb:
        return False

    common = ta & tb

    overlap = len(common) / max(
        1,
        min(len(ta), len(tb)),
    )

    return (
        len(common) >= 3
        and overlap >= 0.60
    )


# =========================================================
# 기사 시간
# =========================================================

def get_entry_time(entry):
    for attr in (
        "published_parsed",
        "updated_parsed",
        "created_parsed",
    ):
        parsed = getattr(entry, attr, None)

        if parsed:
            try:
                return datetime(
                    *parsed[:6],
                    tzinfo=timezone.utc,
                )
            except Exception:
                pass

    return None


def is_recent(dt):
    if dt is None:
        return True

    now = datetime.now(timezone.utc)
    age = now - dt

    if age.total_seconds() < 0:
        return True

    return age <= timedelta(
        hours=MAX_ARTICLE_AGE_HOURS
    )


# =========================================================
# 관련성
# =========================================================

def contains_any(text, terms):
    text = text.lower()

    return any(
        term.lower() in text
        for term in terms
    )


def is_relevant(title, summary, feed_type):
    text = f"{title} {summary}"

    if feed_type == "crypto":
        # 코인 전문 RSS는 기본 허용
        return True

    if feed_type == "stock":
        return (
            contains_any(text, STOCK_TERMS)
            or contains_any(text, MACRO_TERMS)
        )

    if feed_type == "macro":
        return True

    return (
        contains_any(text, CRYPTO_TERMS)
        or contains_any(text, STOCK_TERMS)
        or contains_any(text, MACRO_TERMS)
    )


# =========================================================
# GUID
# =========================================================

def get_guid(entry):
    guid = (
        getattr(entry, "id", None)
        or getattr(entry, "guid", None)
    )

    return str(guid).strip() if guid else ""


# =========================================================
# URL 정리
# =========================================================

def normalize_url(url):
    if not url:
        return ""

    try:
        parsed = urllib.parse.urlsplit(url)

        query = urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        # 추적 파라미터 제거
        query = [
            (k, v)
            for k, v in query
            if not (
                k.lower().startswith("utm_")
                or k.lower()
                in {
                    "gclid",
                    "fbclid",
                    "mc_cid",
                    "mc_eid",
                }
            )
        ]

        return urllib.parse.urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                urllib.parse.urlencode(query),
                "",
            )
        )

    except Exception:
        return url.strip()


def resolve_url(url):
    if not url:
        return ""

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=12,
            allow_redirects=True,
        )

        if response.url:
            return normalize_url(response.url)

    except Exception as e:
        print(
            "URL 확인 실패:",
            str(e)[:120],
        )

    return normalize_url(url)


# =========================================================
# 중복 기록 키
# =========================================================

def hash_key(prefix, value):
    if not value:
        return ""

    return (
        prefix
        + hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()
    )


def make_url_key(url):
    return hash_key(
        "URL:",
        normalize_url(url),
    )


def make_guid_key(guid):
    return hash_key(
        "GUID:",
        guid.strip() if guid else "",
    )


def make_title_key(title):
    return hash_key(
        "TITLE:",
        normalize_title(title),
    )


def make_event_key(title):
    tokens = sorted(event_tokens(title))

    if len(tokens) < 2:
        return ""

    # 제목 단어 전체를 정렬해서 사건 지문 생성
    return hash_key(
        "EVENT:",
        " ".join(tokens),
    )


# =========================================================
# 기록 파일
# =========================================================

def load_sent():
    if not os.path.exists(SENT_FILE):
        return []

    try:
        with open(
            SENT_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            return [
                line.strip()
                for line in f
                if line.strip()
            ]

    except Exception as e:
        print("기록 읽기 실패:", e)
        return []


def save_sent(sent_items):
    try:
        # 순서를 유지하면서 중복 제거
        unique = list(
            dict.fromkeys(sent_items)
        )

        unique = unique[
            -MAX_SENT_HISTORY:
        ]

        with open(
            SENT_FILE,
            "w",
            encoding="utf-8",
        ) as f:
            for item in unique:
                f.write(item + "\n")

    except Exception as e:
        print("기록 저장 실패:", e)


# =========================================================
# 중요도
# =========================================================

def importance_score(item):
    text = (
        item["title"]
        + " "
        + item["summary"]
    ).lower()

    score = 0

    breaking_terms = [
        "breaking",
        "approval",
        "approved",
        "etf approval",
        "rate cut",
        "rate hike",
        "fomc",
        "cpi",
        "jobs report",
        "hack",
        "hacked",
        "exploit",
        "bankruptcy",
        "lawsuit",
        "liquidation",

        "속보",
        "승인",
        "금리 인하",
        "금리인하",
        "금리 인상",
        "금리인상",
        "해킹",
        "파산",
        "소송",
        "청산",
    ]

    for term in breaking_terms:
        if term in text:
            score += 10

    macro = [
        "federal reserve",
        "fed ",
        "fomc",
        "powell",
        "inflation",
        "cpi",
        "ppi",
        "treasury yield",
        "연준",
        "파월",
        "인플레이션",
        "소비자물가",
        "국채금리",
    ]

    for term in macro:
        if term in text:
            score += 6

    crypto_major = [
        "bitcoin", "btc", "비트코인",
        "ethereum", "eth", "이더리움",
        "xrp", "ripple", "리플",
        "solana", "솔라나",
    ]

    for term in crypto_major:
        if term in text:
            score += 4

    stock_major = [
        "nasdaq", "나스닥",
        "s&p 500",
        "dow jones", "다우",
        "nvidia", "엔비디아",
        "tesla", "테슬라",
        "apple", "애플",
        "microsoft", "마이크로소프트",
    ]

    for term in stock_major:
        if term in text:
            score += 4

    if "reuters" in item["source"].lower():
        score += 5

    if item["source"] == "Federal Reserve":
        score += 6

    # 최신 기사 가산점
    published = item.get("published")

    if published:
        age = (
            datetime.now(timezone.utc)
            - published
        ).total_seconds() / 3600

        if age <= 1:
            score += 6
        elif age <= 2:
            score += 4
        elif age <= 4:
            score += 2

    return score


# =========================================================
# Gemini
# =========================================================

client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else None
)


def clean_gemini_text(text):
    if not text:
        return ""

    text = text.strip()

    text = re.sub(
        r"```(?:markdown|text)?",
        "",
        text,
        flags=re.I,
    )

    text = text.replace("```", "")

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def build_news_prompt(item):
    return f"""
너는 한국의 코인·미국증시 전문 뉴스방에서 일하는 뉴스 에디터다.
아래 기사 정보만 사용해서 텔레그램용 한국어 뉴스를 작성한다.

[형식]
- 첫 줄: 구체적이고 자연스러운 한국어 제목
- 본문: 3~5문장
- 마지막 문장: 이 뉴스가 코인시장 또는 미국증시에 왜 중요한지 설명
- 기사에 없는 사실/수치/전망은 절대 만들지 않는다.
- 영어 원문을 그대로 복붙하지 않는다.
- URL, 'RSS', 'AI 요약', '한도 초과' 같은 내부 문구는 출력하지 않는다.
- 존댓말/이모지/투자권유를 사용하지 않는다.
- 출처명은 텔레그램 출력에 절대 표시하지 않는다.
- '출처:', '실제 출처:', 'RSS', 'AI 요약', '한도 초과', '자동 전송' 같은 내부 문구를 절대 출력하지 않는다.
- 제목은 원문의 핵심 사건·수치·기업·자산명을 살려 구체적인 한국어 제목으로 작성한다.
- 본문은 단순히 '관련 최신 기사다'라고 끝내지 말고, 제공된 기사 내용에서 확인되는 사실을 3~5문장으로 구체적으로 설명한다.

[실제 출처]
{item.get("publisher") or item.get("source") or ""}

[원문 제목]
{item.get("title", "")}

[기사 내용]
{clean_text(item.get("summary", ""))[:4500]}
"""


def generate_groq_summary(item):
    """
    Gemini 쿼터 초과 시 GROQ_API_KEY가 있으면 두 번째 AI로 자동 전환.
    별도 SDK 없이 requests만 사용한다.
    """
    if not GROQ_API_KEY:
        return ""

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {
                        "role": "user",
                        "content": build_news_prompt(item),
                    }
                ],
                "temperature": 0.2,
                "max_tokens": 700,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        result = data["choices"][0]["message"]["content"]
        if result:
            print("보조 AI 요약 성공")
            return clean_gemini_text(result)
    except Exception as e:
        print("보조 AI 실패:", str(e)[:200])

    return ""


def fallback_summary(item):
    """
    Gemini와 보조 AI가 모두 사용 불가일 때의 마지막 안전장치.
    출처/RSS/AI 오류 문구는 텔레그램에 절대 노출하지 않는다.
    """
    title = clean_text(item.get("title", ""))
    summary = clean_text(item.get("summary", ""))
    title = re.sub(r"\s+-\s+[^-]{2,60}$", "", title).strip()

    # 영어 원문을 그대로 게시하지 않기 위한 최소 용어 변환
    replacements = [
        (r"(?i)\bcore CPI\b", "근원 소비자물가"),
        (r"(?i)\bCPI\b", "소비자물가지수"),
        (r"(?i)\binflation\b", "인플레이션"),
        (r"(?i)\bfederal reserve\b", "미 연준"),
        (r"(?i)\bFed\b", "연준"),
        (r"(?i)\binterest rates?\b", "금리"),
        (r"(?i)\brate cuts?\b", "금리 인하"),
        (r"(?i)\brate hikes?\b", "금리 인상"),
        (r"(?i)\bbitcoin\b", "비트코인"),
        (r"(?i)\bethereum\b", "이더리움"),
        (r"(?i)\bcrypto(?:currency)?\b", "암호화폐"),
        (r"(?i)\bNasdaq\b", "나스닥"),
        (r"(?i)\bTreasury yields?\b", "미 국채금리"),
        (r"(?i)\bWall Street\b", "미국 증시"),
    ]
    ko_title = title
    for pattern, repl in replacements:
        ko_title = re.sub(pattern, repl, ko_title)

    # 번역이 불완전한 영어 제목은 그대로 노출하지 않는다.
    if len(re.findall(r"[A-Za-z]", ko_title)) > max(12, len(re.findall(r"[가-힣]", ko_title)) * 2):
        kind = item.get("feed_type", "")
        ko_title = {
            "crypto": "암호화폐 시장 주요 뉴스",
            "stock": "미국 증시 주요 뉴스",
            "macro": "미국 경제·금리 주요 뉴스",
        }.get(kind, "글로벌 금융시장 주요 뉴스")

    # AI 둘 다 막힌 경우에도 내부 상태/출처를 노출하지 않는다.
    kind = item.get("feed_type", "")
    body = {
        "crypto": "암호화폐 시장에 영향을 줄 수 있는 주요 소식이 새로 확인됐다. 자세한 내용은 아래 원문에서 확인할 수 있다.",
        "stock": "미국 증시와 주요 기업에 관련된 새로운 소식이 확인됐다. 자세한 내용은 아래 원문에서 확인할 수 있다.",
        "macro": "미국 경제·금리·물가와 관련된 새로운 소식이 확인됐다. 자세한 내용은 아래 원문에서 확인할 수 있다.",
    }.get(kind, "금융시장과 관련된 새로운 소식이 확인됐다. 자세한 내용은 아래 원문에서 확인할 수 있다.")

    return f"{ko_title}\n\n{body}"

def generate_summary(item):
    # 키가 없거나 Gemini를 사용할 수 없어도 뉴스는 계속 전송
    if client is None:
        print("Gemini API 키 없음 - 보조 AI로 전환")
        alt_text = generate_groq_summary(item)
        if alt_text:
            return alt_text
        print("보조 AI 사용 불가 - 기본 요약으로 전송")
        return fallback_summary(item)

    prompt = f"""
너는 한국의 코인·미국증시 전문 뉴스방에서 일하는 최고 수준의 뉴스 에디터다.

아래 기사 정보를 바탕으로 텔레그램에 바로 게시할 한국어 뉴스를 작성한다.

[절대 규칙]

1. 첫 줄에는 가장 중요한 사실이 바로 보이는 한국어 제목을 작성한다.
2. 제목은 자극적으로 낚시하지 말고 실제 기사 내용만 반영한다.
3. 영어 제목은 자연스러운 한국어 제목으로 완전히 바꾼다.
4. 본문은 3~5문장으로 작성한다.
5. 첫 문장에서 가장 중요한 사실부터 설명한다.
6. 가격, 금액, 비율, 기업명, 인물명, 날짜 등 기사에 있는 핵심 수치는 빠뜨리지 않는다.
7. 기사에 없는 사실·수치·전망을 절대 만들어내지 않는다.
8. 같은 내용을 표현만 바꿔 반복하지 않는다.
9. 불필요한 역사 설명이나 장황한 배경 설명은 제거한다.
10. 번역기 같은 문체를 사용하지 않는다.
11. 한국인이 실제 뉴스방에서 읽기 편한 자연스러운 뉴스체로 작성한다.
12. 존댓말을 사용하지 않는다.
13. 투자 권유를 하지 않는다.
14. 상승·하락을 단정적으로 예측하지 않는다.
15. 이모지와 이모티콘을 사용하지 않는다.
16. URL을 출력하지 않는다.
17. 출처 이름을 본문에 억지로 반복하지 않는다.
18. '요약하면', '결론적으로', '포인트는', '쉽게 말하면' 같은 상투적인 머리말을 사용하지 않는다.
19. 마지막 문장은 이 뉴스가 코인시장 또는 미국증시에 왜 중요한지 한 문장으로 설명한다.
20. 원문 정보가 부족하면 부족한 내용을 추측해서 채우지 말고 확인 가능한 내용만 작성한다.
21. RSS 문장을 그대로 복사하지 말고 의미를 유지하면서 자연스럽게 다시 작성한다.
22. 독자가 20초 안에 핵심을 전부 이해할 수 있게 작성한다.
23. 코인 뉴스라면 가격·ETF·규제·거래소·기관 자금·해킹 등 시장 영향 요소를 우선한다.
24. 미국증시 뉴스라면 연준·금리·물가·고용·국채금리·빅테크·반도체·지수 영향 요소를 우선한다.
25. 과장된 분석보다 사실 전달을 최우선으로 한다.

[출력 형식]

제목

본문 3~5문장

마지막 핵심 문장

[출처]
{item["source"]}

[원문 제목]
{item["title"]}

[RSS 기사 내용]
{clean_text(item["summary"])[:4500]}
"""

    for attempt in range(3):
        try:
            result = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
            )

            result_text = getattr(result, "text", "")

            if result_text:
                return clean_gemini_text(result_text)

        except Exception as e:
            error_text = str(e)
            print(
                f"Gemini 실패 {attempt + 1}/3:",
                error_text[:200],
            )

            # 쿼터 초과는 재시도해도 바로 해결되지 않으므로 즉시 fallback
            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
                or "quota" in error_text.lower()
            ):
                print("Gemini 쿼터 초과 - 보조 AI로 전환")
                alt_text = generate_groq_summary(item)
                if alt_text:
                    return alt_text
                print("보조 AI 사용 불가 - 기본 요약으로 전환")
                return fallback_summary(item)

    print("Gemini 요약 최종 실패 - 보조 AI로 전환")
    alt_text = generate_groq_summary(item)
    if alt_text:
        return alt_text
    print("보조 AI 사용 불가 - 기본 요약으로 전환")
    return fallback_summary(item)


# =========================================================
# 텔레그램
# =========================================================

def send_telegram(text, item):
    link = item["final_url"]

    message = (
        f"{text}\n\n"
        f"원문 보기\n"
        f"{link}"
    )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )

    if not response.ok:
        raise RuntimeError(
            f"Telegram 오류 "
            f"{response.status_code}: "
            f"{response.text}"
        )


# =========================================================
# RSS 수집
# =========================================================

def fetch_feed(source, feed_url, feed_type):
    print(f"RSS 확인: {source}")

    try:
        response = requests.get(
            feed_url,
            headers=HEADERS,
            timeout=20,
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

    except Exception as e:
        print(
            f"{source} RSS 실패:",
            str(e)[:150],
        )
        return []

    results = []

    for entry in feed.entries:
        try:
            title = clean_text(
                getattr(entry, "title", "")
            )

            link = str(
                getattr(entry, "link", "")
            ).strip()

            summary = clean_text(
                getattr(entry, "summary", "")
            )

            published = get_entry_time(entry)
            guid = get_guid(entry)

            if not title or not link:
                continue

            if not is_recent(published):
                continue

            if not is_relevant(
                title,
                summary,
                feed_type,
            ):
                continue

            results.append({
                "title": title,
                "summary": summary,
                "feed_url": link,
                "guid": guid,
                "published": published,
                "source": source,
                "feed_type": feed_type,
            })

        except Exception as e:
            print(
                "기사 파싱 실패:",
                str(e)[:100],
            )

    print(
        f"  후보 {len(results)}개"
    )

    return results


# =========================================================
# 메인
# =========================================================

def main():
    print(
        "========================================"
    )
    print(
        "코인·미국증시 뉴스봇 시작"
    )
    print(
        datetime.now(KST).strftime(
            "%Y-%m-%d %H:%M:%S KST"
        )
    )
    print(
        "========================================"
    )

    sent_list = load_sent()
    sent_set = set(sent_list)

    entries = []

    # -----------------------------------------
    # 전체 RSS 수집
    # -----------------------------------------

    for source, url, feed_type in FEEDS:
        entries.extend(
            fetch_feed(
                source,
                url,
                feed_type,
            )
        )

    if not entries:
        print("후보 뉴스 없음")
        return

    # -----------------------------------------
    # 최신순
    # -----------------------------------------

    entries.sort(
        key=lambda x: (
            x["published"]
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ),
        reverse=True,
    )

    candidates = []

    current_urls = set()
    current_guids = set()
    current_titles = []

    # -----------------------------------------
    # 강력 중복 제거
    # -----------------------------------------

    for item in entries:
        feed_url = normalize_url(
            item["feed_url"]
        )

        guid = item["guid"]
        title = item["title"]

        url_key = make_url_key(feed_url)
        guid_key = make_guid_key(guid)
        title_key = make_title_key(title)
        event_key = make_event_key(title)

        # 과거에 보낸 정확한 URL
        if url_key and url_key in sent_set:
            continue

        # 과거 GUID
        if guid_key and guid_key in sent_set:
            continue

        # 과거 정확한 제목
        if title_key and title_key in sent_set:
            continue

        # 동일 실행 URL
        if feed_url in current_urls:
            continue

        # 동일 실행 GUID
        if guid and guid in current_guids:
            continue

        # 서로 다른 언론사의 같은 사건 차단
        duplicate = False

        for old_title in current_titles:
            if same_event_title(
                title,
                old_title,
            ):
                duplicate = True
                break

        if duplicate:
            print(
                "유사 뉴스 제외:",
                title,
            )
            continue

        # 최종 URL 확인
        final_url = resolve_url(feed_url)

        final_url_key = make_url_key(
            final_url
        )

        if (
            final_url_key
            and final_url_key in sent_set
        ):
            continue

        if final_url in current_urls:
            continue

        item["final_url"] = (
            final_url or feed_url
        )

        item["_keys"] = [
            url_key,
            final_url_key,
            guid_key,
            title_key,
            event_key,
        ]

        candidates.append(item)

        current_urls.add(feed_url)
        current_urls.add(item["final_url"])

        if guid:
            current_guids.add(guid)

        current_titles.append(title)

    if not candidates:
        print(
            "새로 보낼 뉴스 없음"
        )
        return

    # -----------------------------------------
    # 중요도 + 최신성으로 최종 순위
    # -----------------------------------------

    candidates.sort(
        key=lambda item: (
            importance_score(item),
            (
                item["published"]
                or datetime.min.replace(
                    tzinfo=timezone.utc
                )
            ).timestamp(),
        ),
        reverse=True,
    )

    # 실행 한 번당 딱 1개
    selected = candidates[
        :MAX_ARTICLES_PER_RUN
    ]

    for item in selected:
        print(
            "선택:",
            item["title"],
        )

        print(
            "출처:",
            item["source"],
        )

        print(
            "중요도:",
            importance_score(item),
        )

        try:
            text = generate_summary(item)
        except Exception as e:
            print("요약 처리 오류 - 기본 요약으로 전환:", str(e)[:200])
            text = fallback_summary(item)

        if not text:
            print("요약 생성 실패 - 전송 안 함")
            continue

        try:
            send_telegram(
                text,
                item,
            )

        except Exception as e:
            print(
                "Telegram 전송 실패:",
                e,
            )
            continue

        # 전송 성공한 뉴스만 중복 기록
        for key in item["_keys"]:
            if key:
                sent_list.append(key)
                sent_set.add(key)

        save_sent(sent_list)

        print(
            "뉴스 1개 전송 완료"
        )

    print(
        "뉴스봇 실행 종료"
    )


if __name__ == "__main__":
    main()
