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

#  한 번 실행할 때 최대 2개
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
            " URL 확인 실패:",
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
            " 전송 기록 읽기 실패:",
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
            " 전송 기록 저장 실패:",
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
    summary = clean_text(item["summary"])
    source = item["source"]

    prompt = f"""
너는 암호화폐·금융 뉴스 전문 요약 에디터다.

아래 RSS 기사 정보를 한국어로 자연스럽게 정리한다.

[작성 규칙]
- 첫 줄은 한국어 기사 제목
- 제목 아래에는 사람이 직접 읽고 정리한 것처럼 자연스러운 4~6문장 요약을 작성한다
- 기사마다 정보량에 따라 4~6문장 사이에서 자연스럽게 분량을 조절한다
- 핵심 내용만 간결하게 작성한다
- 한눈에 이해되도록 중요한 사실부터 쉬운 문장으로 정리한다
- 같은 뜻의 반복, 불필요한 배경설명, 과한 수식어는 제거한다
- 마지막 줄은 기사 핵심을 짧게 정리한다
- 기사에 없는 사실이나 수치를 만들지 않는다
- 영어 기사는 자연스러운 한국어로 번역한다
- 투자 권유나 가격 예측을 하지 않는다
- URL은 작성하지 않는다
- 이모티콘이나 이모지는 사용하지 않는다
- 한국 독자가 읽는 정보방 문체로 작성한다
- 영어 제목은 반드시 자연스러운 한국어 제목으로 바꾼다
- RSS 제목이나 설명을 그대로 복사하지 말고 의미를 이해한 뒤 다시 쓴다
- '포인트만 짚으면', '결론부터 보면' 같은 멘트로 본문을 시작하지 않는다
- 사이트명이나 언론사 도메인을 본문에 반복하지 않는다
- 본문은 번역투 없이 자연스러운 한국어 존댓말이 아닌 뉴스체로 작성한다
- 마지막 한 줄은 앞 내용을 그대로 반복하지 말고 이 뉴스가 왜 중요한지만 짧게 정리한다
- 마지막 핵심 문장에 '요약하자면' 같은 머리말은 붙이지 않는다

[출처]
{source}

[기사 제목]
{title}

[RSS 요약]
{summary[:3500]}
"""

    # 기존에 실제 호출까지 되었던 모델을 그대로 사용.
    # 503이면 같은 모델을 최대 3번 재시도한다.
    for attempt in range(1, 4):
        try:
            print(f" Gemini 요약 생성 중... ({attempt}/3)")

            result = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )

            result_text = getattr(result, "text", None)

            if result_text:
                return clean_gemini_text(result_text)

        except Exception as e:
            print(
                f" Gemini 일시 오류 ({attempt}/3): "
                f"{str(e)[:300]}"
            )

        if attempt < 3:
            time.sleep(5 * attempt)

    # Gemini가 계속 장애여도 기사 자체를 버리지 않는다.
    # RSS 정보로 안전한 대체 본문을 만들어 Telegram 전송을 계속한다.
    print("Gemini 요약 실패 - 이번 기사 전송 보류")
    return ""


# =========================================================
# 랜덤 마지막 문구
# =========================================================

CLOSING_LABELS = [
    "짧게 정리하면",
    "핵심만 보면",
    "한마디로 정리하면",
    "요약하면",
    "결론적으로",
    "핵심은",
    "중요한 점은",
    "정리하면",
    "간단히 보면",
    "이번 소식의 핵심은",
    "시장 관점에서 보면",
    "주목할 부분은",
    "핵심 내용은",
    "쉽게 정리하면",
    "한 줄로 정리하면",
    "결국 중요한 건",
    "이번 뉴스에서 볼 부분은",
    "요점은",
    "간단히 정리하면",
    "결론만 보면",
]


def add_closing_label(text):
    if not text:
        return text

    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(parts) < 2:
        return text

    label = random.choice(CLOSING_LABELS)
    last = parts[-1]
    body = "\n\n".join(parts[:-1])
    return f"{body}\n\n{label}\n{last}"


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
        f"{text}\n\n"f" 원문 보기\n"
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
        f"\n RSS 확인: {source}"
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
            f" {source} RSS 실패:",
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
                " 기사 파싱 실패:",
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
        " 실시간 코인·경제 뉴스봇 시작"
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
                f" {source} 처리 실패:",
                e
            )


    if not entries:

        print(
            "\n 후보 뉴스가 없습니다."
        )

        return


    print(
        f"\n 전체 후보: "
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
                "⏭ URL 중복:",
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
                "⏭ GUID 중복:",
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
                "⏭ 제목 중복:",
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
                "⏭ 유사 기사:",
                item["title"]
            )

            continue


        # -------------------------------------------------
        #  싼 중복 검사 통과 후에만 실제 URL 확인
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
                "⏭ 최종 URL 중복:",
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
            "\n 새로 보낼 뉴스가 없습니다."
        )

        return


    print(
        f"\n 미전송 새 뉴스 "
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
    #  한 번에 최대 2개
    # =====================================================

    selected = new_entries[
        :MAX_ARTICLES_PER_RUN
    ]


    print(
        f" 이번 실행 전송: "
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
            f" {index}/"
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
                    " Gemini 요약 없음"
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
                " 전송 완료"
            )


            # 텔레그램 연속 호출 방지
            time.sleep(1)


        except Exception as e:

            print(
                " 기사 전송 실패:",
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
        " 뉴스봇 실행 종료"
    )

    print(
        "========================================"
    )


if __name__ == "__main__":
    main()
