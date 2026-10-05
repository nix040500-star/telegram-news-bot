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
    "솔라나",
    "스테이블코인",
    "테더",
]


MACRO_TERMS = [
    "federal reserve",
    "fed",
    "fomc",
    "powell",
    "interest rate",
    "rate cut",
    "rate hike",
    "inflation",
    "cpi",
    "ppi",
    "sec",
    "etf",
    "treasury",

    "연준",
    "파월",
    "금리",
    "금리인하",
    "금리인상",
    "인플레이션",
    "소비자물가",
    "물가",
]


# =========================================================
# Google News 검색
# =========================================================

GOOGLE_QUERY = (
    '("코인" OR "암호화폐" OR "가상자산" OR '
    '"비트코인" OR Bitcoin OR BTC OR '
    '"이더리움" OR Ethereum OR ETH OR '
    '"리플" OR Ripple OR XRP OR '
    '"도지코인" OR Dogecoin OR DOGE OR '
    '"솔라나" OR Solana OR SOL OR '
    '"스테이블코인" OR USDT OR USDC OR '
    '"테더" OR Tether OR '
    '"코인베이스" OR Coinbase OR '
    '"바이낸스" OR Binance OR '
    'ETF OR SEC OR '
    '"연준" OR Fed OR FOMC OR '
    '"파월" OR Powell OR '
    '"금리" OR "인플레이션") when:1d'
)


GOOGLE_RSS = (
    "https://news.google.com/rss/search?"
    f"q={urllib.parse.quote(GOOGLE_QUERY)}"
    "&hl=ko&gl=KR&ceid=KR:ko"
)


# =========================================================
# RSS
# =========================================================

FEEDS = [
    (
        "Google News KR",
        GOOGLE_RSS,
        "google"
    ),

    (
        "CoinDesk",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "crypto"
    ),

    (
        "Cointelegraph",
        "https://cointelegraph.com/rss",
        "crypto"
    ),

    (
        "Federal Reserve",
        "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "macro"
    ),

    (
        "Federal Reserve Speeches",
        "https://www.federalreserve.gov/feeds/speeches.xml",
        "macro"
    ),
]


# =========================================================
# 기본 유틸
# =========================================================

def clean_text(text):

    if not text:
        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        str(text)
    )

    text = html.unescape(text)

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_title(title):

    title = clean_text(title).lower()

    title = re.sub(
        r"[^0-9a-z가-힣]+",
        " ",
        title
    )

    return re.sub(
        r"\s+",
        " ",
        title
    ).strip()


def title_similarity(a, b):

    a = normalize_title(a)
    b = normalize_title(b)

    if not a or not b:
        return 0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# =========================================================
# 기사 시간
# =========================================================

def get_entry_time(entry):

    for attr in (
        "published_parsed",
        "updated_parsed"
    ):

        parsed = getattr(
            entry,
            attr,
            None
        )

        if parsed:

            try:

                return datetime(
                    *parsed[:6],
                    tzinfo=timezone.utc
                )

            except Exception:
                pass

    return None


def is_recent(dt):

    # 발행시간 자체가 없는 RSS는
    # 일단 버리지 않고 후보로 사용
    if dt is None:
        return True

    now = datetime.now(timezone.utc)

    age = now - dt

    # 미래 시간으로 잘못 들어온 RSS도 허용
    if age.total_seconds() < 0:
        return True

    return age <= timedelta(
        hours=MAX_ARTICLE_AGE_HOURS
    )


# =========================================================
# 기사 관련성
# =========================================================

def is_relevant(
    title,
    summary,
    feed_type
):

    text = (
        f"{title} {summary}"
    ).lower()

    # 코인 전문 매체
    if feed_type == "crypto":
        return True

    # 연준 공식 RSS
    if feed_type == "macro":
        return True

    return any(
        term.lower() in text
        for term in (
            CRYPTO_TERMS
            + MACRO_TERMS
        )
    )


# =========================================================
# GUID
# =========================================================

def get_guid(entry):

    guid = (
        getattr(entry, "id", None)
        or getattr(entry, "guid", None)
    )

    if not guid:
        return ""

    return str(guid).strip()


# =========================================================
# Google News 등의 중간 URL 실제 주소 확인
# =========================================================

def resolve_url(url):

    if not url:
        return ""

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10,
            allow_redirects=True
        )

        if response.url:
            return response.url.strip()

    except Exception as e:

        print(
            "⚠️ URL 확인 실패:",
            str(e)[:150]
        )

    return url


# =========================================================
# 기록용 키
# =========================================================

def make_url_key(url):

    if not url:
        return ""

    return "URL:" + hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()


def make_guid_key(guid):

    if not guid:
        return ""

    return "GUID:" + hashlib.sha256(
        guid.encode("utf-8")
    ).hexdigest()


def make_title_key(title):

    title = normalize_title(title)

    if not title:
        return ""

    return "TITLE:" + hashlib.sha256(
        title.encode("utf-8")
    ).hexdigest()


# =========================================================
# 전송 기록
# =========================================================

def load_sent():

    if not os.path.exists(SENT_FILE):
        return set()

    try:

        with open(
            SENT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return {
                line.strip()
                for line in f
                if line.strip()
            }

    except Exception as e:

        print(
            "⚠️ 전송 기록 읽기 실패:",
            e
        )

        return set()


def save_sent(sent_items):

    try:

        items = list(sent_items)

        if len(items) > MAX_SENT_HISTORY:
            items = items[
                -MAX_SENT_HISTORY:
            ]

        with open(
            SENT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            for item in items:
                f.write(
                    item + "\n"
                )

    except Exception as e:

        print(
            "⚠️ 전송 기록 저장 실패:",
            e
        )


# =========================================================
# 뉴스 중요도
# =========================================================

def importance_score(item):

    text = (
        item["title"]
        + " "
        + item["summary"]
    ).lower()

    score = 0


    # -----------------------------------------------------
    # 시장 핵심 이벤트
    # -----------------------------------------------------

    very_important = [
        "fomc",
        "rate cut",
        "rate hike",
        "interest rate",
        "금리인하",
        "금리 인하",
        "금리인상",
        "금리 인상",

        "etf approval",
        "etf 승인",

        "sec approval",
        "sec 승인",

        "hack",
        "hacked",
        "exploit",
        "해킹",

        "bankruptcy",
        "파산",

        "lawsuit",
        "소송",

        "liquidation",
        "청산",
    ]

    for term in very_important:

        if term in text:
            score += 8


    # -----------------------------------------------------
    # 연준 / 정책
    # -----------------------------------------------------

    macro_important = [
        "federal reserve",
        "fed ",
        "fomc",
        "powell",
        "연준",
        "파월",
        "inflation",
        "cpi",
        "ppi",
        "인플레이션",
        "소비자물가",
        "sec",
    ]

    for term in macro_important:

        if term in text:
            score += 5


    # -----------------------------------------------------
    # 주요 코인
    # -----------------------------------------------------

    major_coins = [
        "bitcoin",
        "btc",
        "비트코인",

        "ethereum",
        "eth",
        "이더리움",

        "xrp",
        "ripple",
        "리플",

        "solana",
        "솔라나",

        "dogecoin",
        "doge",
        "도지코인",
    ]

    for term in major_coins:

        if term in text:
            score += 3


    # -----------------------------------------------------
    # 주요 기업 / 거래소
    # -----------------------------------------------------

    companies = [
        "coinbase",
        "코인베이스",
        "binance",
        "바이낸스",
        "tether",
        "테더",
    ]

    for term in companies:

        if term in text:
            score += 2


    # 연준 공식 자료 가산점
    if item["feed_type"] == "macro":
        score += 4


    return score


# =========================================================
# Gemini 출력 정리
# =========================================================

def clean_gemini_text(text):

    if not text:
        return ""

    text = text.strip()

    # 코드블록 제거
    text = re.sub(
        r"```(?:markdown|text)?",
        "",
        text,
        flags=re.I
    )

    text = text.replace(
        "```",
        ""
    )

    # 과도한 빈 줄 제거
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# =========================================================
# Gemini
# =========================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


def generate_summary(item):

    title = item["title"]

    summary = clean_text(
        item["summary"]
    )

    source = item["source"]


    # -----------------------------------------------------
    # 기사마다 길이 변화
    # -----------------------------------------------------

    style_roll = random.random()

    if style_roll < 0.15:

        length_guide = (
            "이번 기사는 아주 짧게 쓴다. "
            "제목을 제외한 본문과 핵심 요약을 합쳐 "
            "대략 5줄 안팎으로 끝낸다. "
            "문단 수나 문장 수를 억지로 맞추지 않는다."
        )

    else:

        target_lines = random.randint(
            7,
            10
        )

        length_guide = (
            f"이번 기사는 제목을 제외한 본문과 핵심 요약을 "
            f"대략 {target_lines}줄 안팎으로 쓴다. "
            "정보량에 따라 한두 줄 차이는 괜찮으며 "
            "문단 수와 문장 수를 매번 똑같이 맞추지 않는다."
        )


    prompt = f"""
너는 암호화폐·금융 뉴스 전문 요약 에디터다.

아래 RSS 기사 정보를 한국어로 요약한다.

[작성 규칙]

- 인사말 없이 바로 시작한다.

[이번 기사 길이]

{length_guide}

- 첫 줄에는 자연스러운 한국어 기사 제목을 작성한다.
- 그 아래에 기사 본문을 요약한다.
- 마지막에는 기사 전체 핵심을 1~2줄로 짧게 정리한다.
- 매 기사마다 길이, 문장 수, 문단 수가 조금씩 달라야 한다.
- 항상 같은 틀로 맞추지 않는다.
- 정보가 적으면 억지로 내용을 늘리지 않는다.
- 불필요한 배경 설명과 반복 표현은 제거한다.
- 기사 제목과 RSS 요약에 실제로 포함된 정보만 사용한다.
- 없는 사실, 수치, 인용, 배경을 만들지 않는다.
- 영어 기사는 자연스러운 한국어로 번역·요약한다.
- 전문용어는 일반인이 이해하기 쉽게 풀어쓴다.
- 같은 내용을 반복하지 않는다.
- 투자 권유를 하지 않는다.
- 가격 상승·하락을 임의로 예측하지 않는다.
- 코인명, 기업명, 인물명, 중요한 수치와 날짜는 유지한다.
- 연준, SEC, 정부, 정책 관련 내용은 사실 중심으로 중립적으로 작성한다.
- 딱딱한 AI 문체보다 사람이 뉴스를 읽고 직접 정리해 전달하는 자연스러운 문체를 사용한다.
- URL을 작성하지 않는다.
- '기사 원문 보러가기' 같은 문구를 작성하지 않는다.

[마지막 핵심 문장]

- 본문 아래에 핵심 내용을 보통 1~2줄로 작성한다.
- 아주 짧은 기사라면 1줄이면 충분하다.
- 마지막 핵심 문장 앞에는 머리말을 붙이지 않는다.
- '요약하자면', '쉽게 말씀드리면', '핵심만 말씀드리면' 같은 표현을 직접 쓰지 않는다.
- 해당 머리말은 Python 프로그램에서 별도로 추가한다.

[출처]

{source}

[기사 제목]

{title}

[RSS 요약]

{summary[:3500]}
"""


    print("🤖 Gemini 요약 생성 중...")


    result = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )


    if (
        not result
        or not getattr(
            result,
            "text",
            None
        )
    ):
        return ""


    return clean_gemini_text(
        result.text
    )


# =========================================================
# 랜덤 마지막 문구
# =========================================================

CLOSING_LABELS = [
    "🔎 요약하자면..",
    "🔎 짧게 말씀드리면..",
    "🔎 한 줄로 말씀드리면..",
    "🔎 두 줄로 짧게 말씀드리면..",
    "🔎 쉽게 말씀드리면..",
    "🔎 간단히 정리하면..",
    "🔎 핵심만 말씀드리면..",
    "🔎 결론적으로 보면..",
    "🔎 지금 상황만 보면..",
    "🔎 쉽게 풀어보면..",
]


def add_closing_label(text):

    lines = [
        line.rstrip()
        for line in text.splitlines()
    ]

    # 빈 줄 제거
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return text

    # 마지막 문단을 핵심 요약으로 취급
    last = lines[-1].strip()

    label = random.choice(
        CLOSING_LABELS
    )

    # 마지막 줄 앞에 랜덤 라벨
    lines[-1] = (
        f"{label}\n{last}"
    )

    return "\n".join(lines)


# =========================================================
# 텔레그램 전송
# =========================================================

def send_telegram(
    text,
    item
):

    link = item["final_url"]

    published = item["published"]

    if published:

        time_text = (
            published
            .astimezone(KST)
            .strftime(
                "%Y.%m.%d %H:%M"
            )
        )

    else:

        time_text = (
            datetime.now(KST)
            .strftime(
                "%Y.%m.%d %H:%M"
            )
        )


    message = (
        f"{text}\n\n"
        f"🕐 {time_text} KST\n"
        f"📰 출처 : {item['source']}\n\n"
        f"🔗 기사 원문\n"
        f"{link}"
    )


    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )


    response = requests.post(
        url,
        data={
            "chat_id":
                TELEGRAM_CHAT_ID,

            "text":
                message,

            "disable_web_page_preview":
                True,
        },
        timeout=20
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

def fetch_feed(
    source,
    feed_url,
    feed_type
):

    print(
        f"\n📡 RSS 확인: {source}"
    )


    try:

        response = requests.get(
            feed_url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

    except Exception as e:

        print(
            f"❌ {source} RSS 실패:",
            e
        )

        return []


    results = []


    for entry in feed.entries:

        try:

            title = clean_text(
                getattr(
                    entry,
                    "title",
                    ""
                )
            )

            link = str(
                getattr(
                    entry,
                    "link",
                    ""
                )
            ).strip()

            summary = clean_text(
                getattr(
                    entry,
                    "summary",
                    ""
                )
            )

            published = get_entry_time(
                entry
            )

            guid = get_guid(
                entry
            )


            if not title:
                continue

            if not link:
                continue

            if not is_recent(
                published
            ):
                continue

            if not is_relevant(
                title,
                summary,
                feed_type
            ):
                continue


            results.append({
                "title":
                    title,

                "summary":
                    summary,

                "feed_url":
                    link,

                "guid":
                    guid,

                "published":
                    published,

                "source":
                    source,

                "feed_type":
                    feed_type,
            })


        except Exception as e:

            print(
                "⚠️ 기사 파싱 실패:",
                e
            )


    print(
        f"   후보 {len(results)}개"
    )


    return results


# =========================================================
# 메인
# =========================================================

def main():

    print(
        "\n"
        "========================================"
    )

    print(
        "🚀 실시간 코인·경제 뉴스봇 시작"
    )

    print(
        datetime.now(KST).strftime(
            "%Y-%m-%d %H:%M:%S KST"
        )
    )

    print(
        "========================================"
    )


    sent_items = load_sent()


    # =====================================================
    # RSS 전체 수집
    # =====================================================

    entries = []


    for (
        source,
        url,
        feed_type
    ) in FEEDS:

        try:

            entries.extend(
                fetch_feed(
                    source,
                    url,
                    feed_type
                )
            )

        except Exception as e:

            print(
                f"❌ {source} 처리 실패:",
                e
            )


    if not entries:

        print(
            "\n✅ 후보 뉴스가 없습니다."
        )

        return


    print(
        f"\n📥 전체 후보: "
        f"{len(entries)}개"
    )


    # =====================================================
    # 최신 기사 우선
    # =====================================================

    entries.sort(
        key=lambda x:
            x["published"]
            or datetime.min.replace(
                tzinfo=timezone.utc
            ),
        reverse=True
    )


    # =====================================================
    # 저렴한 중복 검사부터 실행
    # =====================================================

    new_entries = []

    current_urls = set()
    current_guids = set()
    current_titles = []


    for item in entries:

        feed_url = item["feed_url"]

        guid = item["guid"]


        url_key = make_url_key(
            feed_url
        )

        guid_key = make_guid_key(
            guid
        )

        title_key = make_title_key(
            item["title"]
        )


        # -------------------------------------------------
        # 이미 전송한 feed URL
        # -------------------------------------------------

        if (
            url_key
            and url_key in sent_items
        ):

            print(
                "⏭️ URL 중복:",
                item["title"]
            )

            continue


        # -------------------------------------------------
        # 이미 전송한 GUID
        # -------------------------------------------------

        if (
            guid_key
            and guid_key in sent_items
        ):

            print(
                "⏭️ GUID 중복:",
                item["title"]
            )

            continue


        # -------------------------------------------------
        # 정확히 같은 제목
        # -------------------------------------------------

        if (
            title_key
            and title_key in sent_items
        ):

            print(
                "⏭️ 제목 중복:",
                item["title"]
            )

            continue


        # -------------------------------------------------
        # 이번 실행 내 URL 중복
        # -------------------------------------------------

        if (
            feed_url
            and feed_url in current_urls
        ):
            continue


        # -------------------------------------------------
        # 이번 실행 내 GUID 중복
        # -------------------------------------------------

        if (
            guid
            and guid in current_guids
        ):
            continue


        # -------------------------------------------------
        # 비슷한 제목 기사 제거
        # -------------------------------------------------

        duplicate_title = False

        for old_title in current_titles:

            if (
                title_similarity(
                    item["title"],
                    old_title
                )
                >= TITLE_SIMILARITY
            ):

                duplicate_title = True
                break


        if duplicate_title:

            print(
                "⏭️ 유사 기사:",
                item["title"]
            )

            continue


        # -------------------------------------------------
        # ★ 싼 중복 검사 통과 후에만 실제 URL 확인
        # -------------------------------------------------

        final_url = resolve_url(
            feed_url
        )


        final_url_key = make_url_key(
            final_url
        )


        if (
            final_url_key
            and final_url_key
            in sent_items
        ):

            print(
                "⏭️ 최종 URL 중복:",
                item["title"]
            )

            continue


        if (
            final_url
            and final_url
            in current_urls
        ):
            continue


        item["final_url"] = (
            final_url
            or feed_url
        )


        new_entries.append(
            item
        )


        if feed_url:
            current_urls.add(
                feed_url
            )

        if final_url:
            current_urls.add(
                final_url
            )

        if guid:
            current_guids.add(
                guid
            )

        current_titles.append(
            item["title"]
        )


    # =====================================================
    # 새 뉴스 없음
    # =====================================================

    if not new_entries:

        print(
            "\n✅ 새로 보낼 뉴스가 없습니다."
        )

        return


    print(
        f"\n🔥 미전송 새 뉴스 "
        f"{len(new_entries)}개 발견"
    )


    # =====================================================
    # 중요도 + 최신성
    # =====================================================

    def ranking(item):

        importance = importance_score(
            item
        )

        published = (
            item["published"]
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        )

        return (
            importance,
            published.timestamp()
        )


    new_entries.sort(
        key=ranking,
        reverse=True
    )


    # =====================================================
    # ★ 한 번에 최대 2개
    # =====================================================

    selected = new_entries[
        :MAX_ARTICLES_PER_RUN
    ]


    print(
        f"🏆 이번 실행 전송: "
        f"{len(selected)}개"
    )


    for index, item in enumerate(
        selected,
        1
    ):

        print(
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        print(
            f"📰 {index}/"
            f"{len(selected)} | "
            f"{item['source']}"
        )

        print(
            "제목:",
            item["title"]
        )

        print(
            "중요도:",
            importance_score(item)
        )

        print(
            "링크:",
            item["final_url"]
        )


        try:

            # ---------------------------------------------
            # Gemini 요약
            # ---------------------------------------------

            text = generate_summary(
                item
            )


            if not text:

                print(
                    "❌ Gemini 요약 없음"
                )

                continue


            # ---------------------------------------------
            # 랜덤 핵심 라벨
            # ---------------------------------------------

            text = add_closing_label(
                text
            )


            # ---------------------------------------------
            # Telegram
            # ---------------------------------------------

            send_telegram(
                text,
                item
            )


            # ---------------------------------------------
            # 성공한 뉴스만 기록
            # ---------------------------------------------

            keys = [
                make_url_key(
                    item["feed_url"]
                ),

                make_url_key(
                    item["final_url"]
                ),

                make_guid_key(
                    item["guid"]
                ),

                make_title_key(
                    item["title"]
                ),
            ]


            for key in keys:

                if key:
                    sent_items.add(
                        key
                    )


            # 기사 하나 성공할 때마다 저장
            save_sent(
                sent_items
            )


            print(
                "✅ 전송 완료"
            )


            # 텔레그램 연속 호출 방지
            time.sleep(1)


        except Exception as e:

            print(
                "❌ 기사 전송 실패:",
                e
            )

            # 기사 하나 실패해도
            # 다음 뉴스 계속 진행
            continue


    print(
        "\n"
        "========================================"
    )

    print(
        "✅ 뉴스봇 실행 종료"
    )

    print(
        "========================================"
    )


if __name__ == "__main__":
    main()
