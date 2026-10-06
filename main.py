import os
import re
import html
import hashlib
import urllib.parse
import random
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
    text = re.sub(r"```(?:markdown|text)?", "", text, flags=re.I)
    text = text.replace("```", "")
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 모델이 실수로 붙여도 텔레그램에는 내부 문구/URL을 노출하지 않는다.
    bad_prefixes = (
        "출처:", "실제 출처:", "원문 보기", "RSS:", "URL:",
        "링크:", "기사 링크:", "원문 링크:",
    )
    cleaned = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            cleaned.append("")
            continue
        if s.startswith(bad_prefixes):
            continue
        if re.fullmatch(r"https?://\S+", s, flags=re.I):
            continue
        cleaned.append(line.rstrip())

    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


WRAP_UP_LABELS = [
    "쉽게 정리해드리면", "간단히 말씀드리면", "한마디로 정리하면", "딱 정리해보면",
    "결국 핵심은 이겁니다", "그래서 무슨 말이냐면", "쉽게 풀어보면", "핵심만 말씀드리면",
    "결론만 먼저 말씀드리면", "시장 입장에서 보면", "지금 중요한 건 이겁니다", "딱 두 줄로 보면",
    "짧게 정리해드리면", "한 번에 정리하면", "쉽게 이해하시면 이렇습니다", "결국 봐야 할 건 이겁니다",
    "지금 상황을 정리하면", "핵심만 뽑아보면", "중요한 부분만 보면", "결국 이야기는 간단합니다",
    "쉽게 말씀드리자면", "한 줄씩 정리해보면", "정리해서 말씀드리면", "시장에서는 이렇게 보면 됩니다",
    "결국 포인트는 이겁니다", "간단하게 풀면 이렇습니다", "지금까지 내용을 묶어보면", "핵심을 다시 보면",
    "쉽게 보면 이런 얘기입니다", "결국 시장이 보는 건 이겁니다", "딱 필요한 부분만 보면", "요지만 말씀드리면",
    "이걸 쉽게 바꿔 말하면", "지금 흐름만 놓고 보면", "결국 중요한 건 두 가지입니다", "시장 기준으로 풀어보면",
    "한마디로 말씀드리면", "조금 더 쉽게 설명드리면", "결국 이렇게 보시면 됩니다", "짧게 풀어드리면",
    "지금 뉴스의 핵심은 이겁니다", "결국 시장에 중요한 건", "내용을 쉽게 정리하면", "딱 핵심만 남기면",
    "이 소식을 쉽게 보면", "결국 무슨 이야기냐면", "두 가지만 기억하시면 됩니다", "핵심만 다시 말씀드리면",
    "시장에선 이렇게 받아들이면 됩니다", "간단히 풀어서 보면", "결국 체크할 부분은 이겁니다", "지금 포인트만 보면",
    "쉽게 설명하면 이렇습니다", "한 번 더 정리해보면", "이 뉴스에서 볼 건 이겁니다", "결국 핵심만 보면",
    "시장 영향만 놓고 보면", "지금 상황을 쉽게 보면", "딱 알아두실 건 이겁니다", "간단하게 말씀드리자면",
    "결국 이렇게 이해하시면 됩니다", "뉴스를 쉽게 풀면", "핵심 내용만 묶으면", "지금 시장이 보는 부분은",
    "한눈에 정리하면", "결국 중요한 부분은", "쉽게 바꿔서 말씀드리면", "시장 쪽에서 보면",
    "짧고 쉽게 말씀드리면", "이 뉴스의 요지는", "결국 두 줄로 정리하면", "핵심만 콕 집으면",
    "지금 알아두실 건", "시장 관점에서 정리하면", "쉽게 말해서 이런 상황입니다", "결국 흐름은 이렇습니다",
    "내용을 한 번 묶어보면", "딱 핵심만 설명드리면", "이걸 시장 관점으로 보면", "결국 봐야 하는 부분은",
    "간단하게 이해하면", "지금 뉴스만 놓고 보면", "핵심을 두 줄로 줄이면", "결국 시장의 관심은",
    "쉽게 정리해서 보면", "이 소식의 핵심만 보면", "시장에 중요한 부분만 보면", "한마디로 풀어보면",
    "지금까지 나온 내용만 보면", "결국 체크포인트는", "간단히 이해하시면", "핵심을 쉽게 풀면",
    "딱 두 가지만 보면", "시장 반응을 생각하면", "결국 이 부분이 중요합니다", "쉽게 정리하면 이렇습니다",
    "뉴스의 핵심을 잡아보면", "지금 시점에서 중요한 건", "결국 시장에는 이렇게 읽힙니다", "짧게 핵심만 보면",
    "한 번에 이해하시려면", "이걸 두 줄로 줄이면", "결국 알아둘 건 이겁니다", "시장 기준으로 정리하면",
    "쉽게 이해할 포인트는", "지금 내용의 핵심은", "결국 이 뉴스가 말하는 건", "간단히 핵심만 보면",
    "시장에 미치는 부분만 보면", "딱 필요한 내용만 정리하면", "결국 이렇게 정리됩니다", "쉽게 풀어서 말씀드리면",
    "핵심부터 다시 보면", "지금 가장 중요한 부분은", "한마디로 보면", "결국 시장에서 볼 건",
    "짧게 두 줄로 정리하면", "이 뉴스만 쉽게 보면", "핵심만 빠르게 보면", "결국 중요한 이야기는",
    "시장 입장에서 핵심만 보면", "쉽게 두 줄로 정리하면", "지금 알아야 할 핵심은", "결국 요점은 이겁니다",
]

def choose_wrap_up_label():
    return random.choice(WRAP_UP_LABELS)


def build_news_prompt(item):
    line_target = random.randint(6, 12)
    wrap_label = choose_wrap_up_label()

    return f"""
당신은 텔레그램에서 코인·미국증시 뉴스를 직접 설명해주는 한국인 운영자입니다.
딱딱한 기사체나 번역기 말투가 아니라, 사람이 독자에게 자연스럽게 설명해주는 존댓말로 작성하세요.

[이번 뉴스 작성 방식]
- 첫 줄은 자연스러운 한국어 제목 1줄입니다.
- 그 다음 본문은 대략 {line_target}줄 분량으로 작성하세요.
- 본문 요약은 휴대폰 화면에서 보이는 줄 수를 기준으로 6~12줄 사이에서 매번 랜덤한 길이로 작성하세요. 절대로 한 덩어리로 붙여 쓰지 마세요.
- 본문을 2~4개의 짧은 문단으로 나누고, 각 문단 사이에는 반드시 빈 줄을 1줄 넣으세요.
- 한 문단은 1~2문장 정도로 짧게 유지해서 휴대폰에서 한눈에 읽히게 하세요.
- 같은 의미를 반복하지 말고 핵심 사실과 시장에 필요한 맥락만 남기세요.
- 문장 수와 문장 길이를 매번 똑같이 맞추지 마세요.
- 마지막에는 아래 마무리 문구를 정확히 한 번 넣고, 그 아래 핵심을 2줄 중심으로 정리하되 화면상 최대 3줄을 넘기지 마세요.
- 마무리 문구 아래 핵심 정리는 휴대폰 화면 기준으로 2~3줄 안에 끝내세요. 너무 짧은 한두 마디가 아니라, 사건의 핵심과 시장에서 봐야 할 점이 바로 이해되도록 압축해서 작성하세요.
- 이번 마무리 문구: "{wrap_label}"

[말투]
- 친한 사람에게 뉴스를 이해하기 쉽게 설명해주는 자연스러운 존댓말을 사용하세요.
- "최근 시장에서는 ~라는 걱정이 있었는데요.", "이 부분은 꽤 눈여겨볼 만합니다.",
  "다만 이것만으로 방향이 정해졌다고 보기는 어렵습니다."처럼 문맥에 맞게 자연스럽게 이어가세요.
- 모든 문장을 억지로 "~습니다" 하나로 끝내지 마세요.
- "~인데요", "~겠죠", "~볼 수 있습니다", "~가능성이 있습니다", "~상황입니다",
  "~나온 셈입니다" 등을 문맥에 맞게 섞되 같은 종결을 연달아 반복하지 마세요.
- 반말, 음슴체, 논문체, 보도자료체, 번역체는 금지합니다.
- "분위기가 형성됐습니다", "중요한 영향을 미칩니다"처럼 로봇 같은 상투 표현은 가급적 피하세요.
- 기사 제목을 본문 첫 문장에서 그대로 다시 반복하지 마세요.

[내용]
- 제공된 기사 정보에서 확인되는 사실만 사용하세요.
- 기사에 없는 수치·사건·전망은 만들지 마세요.
- 핵심 수치, 기업명, 인물명, 자산명은 기사에 있다면 빠뜨리지 마세요.
- 시장 영향은 근거가 있을 때만 설명하고, 확정되지 않은 내용은 단정하지 마세요.
- 코인·미국증시 독자가 "그래서 이게 나한테 왜 중요한데?"를 이해할 수 있게 설명하세요.
- 투자 권유는 하지 마세요.

[절대 출력 금지]
- 출처명
- URL
- "원문 보기"
- RSS
- AI 요약, 한도 초과, 자동 전송 같은 내부 문구
- 이모지
- 불필요한 영어 원문 복사

[출력 예시 구조]
자연스러운 한국어 제목

자연스러운 설명...
자연스러운 설명...
(전체 본문은 이번에 약 {line_target}줄)

{wrap_label}
짧은 핵심 정리 첫 번째 줄
짧은 핵심 정리 두 번째 줄

[원문 제목]
{item.get("title", "")}

[기사 내용]
{clean_text(item.get("summary", ""))[:4500]}
"""


def generate_groq_summary(item):
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
                        "role": "system",
                        "content": (
                            "당신은 한국 금융 뉴스방 운영자입니다. "
                            "사람이 직접 설명하듯 자연스러운 존댓말을 쓰고, "
                            "딱딱한 기사체와 번역체를 피합니다."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_news_prompt(item),
                    },
                ],
                "temperature": 0.55,
                "max_tokens": 1600,
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


def is_incomplete_summary(text):
    """제목만 나오거나 본문이 거의 없는 AI 응답을 걸러낸다."""
    if not text:
        return True
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(lines) < 5:
        return True
    # 제목을 제외한 실제 내용이 너무 짧으면 실패로 본다.
    body_chars = len("".join(lines[1:]))
    return body_chars < 120


def fallback_summary(item):
    # 두 AI가 모두 실패하면 영어/RSS/출처를 그대로 뿌리지 않고 안전하게 짧게 전송한다.
    kind = item.get("feed_type", "")
    title = {
        "crypto": "암호화폐 시장 주요 소식",
        "stock": "미국 증시 주요 소식",
        "macro": "미국 경제·금리 주요 소식",
    }.get(kind, "글로벌 금융시장 주요 소식")

    wrap_label = choose_wrap_up_label()
    body = {
        "crypto": "암호화폐 시장과 관련해 새로운 소식이 확인됐습니다.",
        "stock": "미국 증시와 주요 기업에 관련된 새로운 소식이 확인됐습니다.",
        "macro": "미국 경제와 금리 흐름에 관련된 새로운 소식이 확인됐습니다.",
    }.get(kind, "금융시장과 관련된 새로운 소식이 확인됐습니다.")

    return (
        f"{title}\n\n{body}\n"
        f"현재 확보된 기사 정보가 짧아 확인되지 않은 내용을 임의로 덧붙이지 않았습니다.\n\n"
        f"{wrap_label}\n"
        f"확인된 내용만 간단히 전달드렸습니다.\n"
        f"제목을 누르면 원문 내용을 직접 확인하실 수 있습니다."
    )


def generate_summary(item):
    if client is None:
        print("Gemini API 키 없음 - 보조 AI로 전환")
        alt_text = generate_groq_summary(item)
        return alt_text or fallback_summary(item)

    prompt = build_news_prompt(item)

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
            print(f"Gemini 실패 {attempt + 1}/3:", error_text[:200])

            # 쿼터 초과는 기다리지 않고 즉시 Groq로 넘긴다.
            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
                or "quota" in error_text.lower()
            ):
                print("Gemini 쿼터 초과 - 보조 AI로 전환")
                alt_text = generate_groq_summary(item)
                return alt_text or fallback_summary(item)

    print("Gemini 요약 최종 실패 - 보조 AI로 전환")
    alt_text = generate_groq_summary(item)
    return alt_text or fallback_summary(item)


# =========================================================
# 텔레그램
# =========================================================

def send_telegram(text, item):
    if is_incomplete_summary(text):
        raise RuntimeError("AI 요약이 제목만 생성되어 전송을 중단했습니다.")

    link = item["final_url"]

    lines = text.strip().splitlines()
    title = lines[0].strip() if lines else "뉴스 확인"
    rest = lines[1:]

    # 마무리 멘트가 시작되는 위치를 찾아 원문 링크를 그 바로 위에 넣는다.
    wrap_index = None
    for i, line in enumerate(rest):
        if line.strip() in WRAP_UP_LABELS:
            wrap_index = i
            break

    if wrap_index is None:
        body_lines = rest
        wrap_lines = []
    else:
        body_lines = rest[:wrap_index]
        wrap_lines = rest[wrap_index:]

    body = "\n".join(body_lines).strip()
    wrap = "\n".join(wrap_lines).strip()

    safe_title = html.escape(title)
    safe_body = html.escape(body)
    safe_wrap = html.escape(wrap)
    safe_link = html.escape(link, quote=True)

    parts = [f"<b>{safe_title}</b>"]

    if safe_body:
        parts.append(safe_body)

    if safe_wrap:
        parts.append(safe_wrap)

    # 핵심 2줄까지 모두 보여준 뒤 맨 아래에 원문 하이퍼링크 배치
    parts.append(f'<a href="{safe_link}">원문 기사</a>')

    message = "\n\n".join(parts)

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )

    if not response.ok:
        raise RuntimeError(
            f"Telegram 오류 {response.status_code}: {response.text}"
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
