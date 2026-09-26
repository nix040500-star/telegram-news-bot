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
]


# =========================================================
# 전송 기록
# =========================================================

def load_sent_items():
    if not os.path.exists(SENT_FILE):
        return set()

    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return {
                line.strip()
                for line in f
                if line.strip()
            }

    except Exception as e:
        print("⚠️ 전송 기록 읽기 실패:", e)
        return set()


def save_sent_items(items):
    items = [
        x.strip()
        for x in items
        if x and x.strip()
    ]

    if not items:
        return

    with open(SENT_FILE, "a", encoding="utf-8") as f:
        for item in items:
            f.write(item + "\n")


# =========================================================
# 제목 / URL 정리
# =========================================================

def strip_source_suffix(title):
    title = (title or "").strip()

    parts = re.split(r"\s+-\s+", title)

    if len(parts) > 1 and len(parts[-1]) <= 40:
        title = " - ".join(parts[:-1])

    return title.strip()


def normalize_title(title):
    title = strip_source_suffix(title).lower()

    title = re.sub(
        r"https?://\S+",
        "",
        title
    )

    title = re.sub(
        r"[^가-힣a-z0-9]+",
        " ",
        title
    )

    return re.sub(
        r"\s+",
        " ",
        title
    ).strip()


def make_title_key(title):
    normalized = normalize_title(title)

    if not normalized:
        return ""

    digest = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()

    return "TITLE:" + digest


def make_guid_key(entry):
    guid = (
        entry.get("id")
        or entry.get("guid")
        or ""
    )

    guid = str(guid).strip()

    return "GUID:" + guid if guid else ""


def canonicalize_url(url):
    if not url:
        return ""

    try:
        p = urllib.parse.urlsplit(url.strip())

        query = urllib.parse.parse_qsl(
            p.query,
            keep_blank_values=True
        )

        tracking = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "utm_id",
            "gclid",
            "fbclid",
            "mc_cid",
            "mc_eid"
        }

        query = [
            (k, v)
            for k, v in query
            if k.lower() not in tracking
        ]

        clean_query = urllib.parse.urlencode(
            query,
            doseq=True
        )

        return urllib.parse.urlunsplit(
            (
                p.scheme.lower(),
                p.netloc.lower(),
                p.path.rstrip("/"),
                clean_query,
                ""
            )
        )

    except Exception:
        return url.strip()


# =========================================================
# 기사 날짜
# =========================================================

def parse_date(entry):

    candidates = [
        entry.get("published"),
        entry.get("updated"),
        entry.get("created"),
    ]

    for value in candidates:

        if not value:
            continue

        try:
            dt = email.utils.parsedate_to_datetime(value)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt.astimezone(timezone.utc)

        except Exception:
            pass


    for key in (
        "published_parsed",
        "updated_parsed",
        "created_parsed"
    ):

        value = entry.get(key)

        if value:

            try:
                return datetime(
                    value.tm_year,
                    value.tm_mon,
                    value.tm_mday,
                    value.tm_hour,
                    value.tm_min,
                    value.tm_sec,
                    tzinfo=timezone.utc
                )

            except Exception:
                pass

    return None


# =========================================================
# 실제 기사 URL 확인
# =========================================================

def resolve_url(url):

    if not url:
        return ""

    try:

        r = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
            allow_redirects=True
        )

        final_url = canonicalize_url(r.url)

        if final_url.startswith("http"):
            return final_url

    except Exception as e:
        print("⚠️ URL 확인 실패:", e)

    return canonicalize_url(url)


# =========================================================
# 사이트 도메인 추출
# =========================================================

def get_site_domain(url):

    if not url:
        return "기사 링크"

    try:

        parsed = urllib.parse.urlsplit(url)

        domain = parsed.netloc.lower().strip()

        if domain.startswith("www."):
            domain = domain[4:]

        if domain:
            return domain

    except Exception:
        pass

    return "기사 링크"


# =========================================================
# 뉴스 관련성 확인
# =========================================================

def is_relevant(title, summary, feed_type):

    text = f"{title} {summary}".lower()

    if feed_type in ("crypto", "google"):

        return any(
            term.lower() in text
            for term in CRYPTO_TERMS + MACRO_TERMS
        )


    if feed_type == "macro":

        crypto_hit = any(
            term.lower() in text
            for term in CRYPTO_TERMS
        )

        major_macro = any(
            term in text
            for term in [
                "fomc",
                "federal funds",
                "interest rate",
                "monetary policy",
                "powell",
                "inflation",
                "rate",
                "digital asset",
                "crypto",
                "stablecoin"
            ]
        )

        return crypto_hit or major_macro

    return True


# =========================================================
# 유사 뉴스 중복 제거
# =========================================================

def titles_are_same(a, b):

    a = normalize_title(a)
    b = normalize_title(b)

    if not a or not b:
        return False

    if a == b:
        return True


    if SequenceMatcher(
        None,
        a,
        b
    ).ratio() >= 0.78:

        return True


    stopwords = {
        "및", "등", "관련", "대한", "통해",
        "위해", "에서", "으로", "한다",
        "발표", "전망", "가능성",
        "the", "a", "an", "to", "of",
        "in", "on", "for", "and",
        "with", "as", "is", "are",
        "says", "said"
    }


    aw = {
        x for x in a.split()
        if len(x) >= 2
        and x not in stopwords
    }

    bw = {
        x for x in b.split()
        if len(x) >= 2
        and x not in stopwords
    }


    if not aw or not bw:
        return False


    common = aw & bw

    overlap_small = (
        len(common)
        / min(len(aw), len(bw))
    )

    overlap_union = (
        len(common)
        / len(aw | bw)
    )


    return (
        (
            len(common) >= 3
            and overlap_small >= 0.60
        )
        or
        (
            len(common) >= 4
            and overlap_union >= 0.45
        )
    )


# =========================================================
# Gemini 결과 정리
# =========================================================

def clean_gemini_text(text):

    if not text:
        return ""

    text = text.strip()

    text = re.sub(
        r"\n*🔗\s*\[기사 원문 보러가기\]\([^)]+\)",
        "",
        text
    )

    text = re.sub(
        r"\n*https?://\S+\s*$",
        "",
        text
    )

    return text.strip()


def escape_markdown_url(url):

    return (
        url
        .replace("(", "%28")
        .replace(")", "%29")
    )


# =========================================================
# Telegram 전송
# =========================================================

def send_telegram(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:

        print("❌ Telegram 환경변수 없음")
        return False


    api_url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )


    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }


    try:

        r = requests.post(
            api_url,
            json=payload,
            timeout=30
        )

        print("📡 Telegram:", r.status_code)


        if r.status_code == 200:
            return True


        print(
            "⚠️ Markdown 전송 실패, 일반 텍스트로 재시도:",
            r.text
        )


        payload.pop("parse_mode", None)


        r = requests.post(
            api_url,
            json=payload,
            timeout=30
        )


        print(
            "📡 Telegram 재시도:",
            r.status_code
        )


        if r.status_code != 200:

            print(
                "❌ Telegram 오류:",
                r.text
            )

            return False


        return True


    except Exception as e:

        print(
            "❌ Telegram 요청 오류:",
            e
        )

        return False


# =========================================================
# RSS 수집
# =========================================================

def fetch_all_entries():

    collected = []


    for source, feed_url, feed_type in FEEDS:

        print(
            f"\n🔎 {source} 확인 중..."
        )


        try:

            r = requests.get(
                feed_url,
                headers=HEADERS,
                timeout=20
            )


            if r.status_code != 200:

                print(
                    f"❌ {source} HTTP "
                    f"{r.status_code}"
                )

                continue


            feed = feedparser.parse(
                r.content
            )


            if getattr(
                feed,
                "bozo",
                False
            ):

                print(
                    f"⚠️ {source} RSS 경고:",
                    getattr(
                        feed,
                        "bozo_exception",
                        ""
                    )
                )


            entries = list(
                feed.entries or []
            )


            print(
                f"📰 {source}: "
                f"{len(entries)}개"
            )


            for entry in entries:

                title = str(
                    entry.get(
                        "title",
                        ""
                    )
                ).strip()


                link = str(
                    entry.get(
                        "link",
                        ""
                    )
                ).strip()


                summary = str(
                    entry.get(
                        "summary",
                        ""
                    )
                    or
                    entry.get(
                        "description",
                        ""
                    )
                ).strip()


                published = parse_date(
                    entry
                )


                if (
                    not title
                    or not link
                    or not published
                ):
                    continue


                if not is_relevant(
                    title,
                    summary,
                    feed_type
                ):
                    continue


                collected.append({

                    "source": source,

                    "feed_type":
                        feed_type,

                    "entry":
                        entry,

                    "title":
                        title,

                    "summary":
                        summary,

                    "feed_url":
                        canonicalize_url(
                            link
                        ),

                    "published":
                        published,

                    "guid_key":
                        make_guid_key(
                            entry
                        ),

                    "title_key":
                        make_title_key(
                            title
                        ),
                })


        except Exception as e:

            print(
                f"❌ {source} 수집 오류:",
                e
            )

            continue


    return collected


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "\n======================================"
    )

    print(
        "🚀 MULTI-SOURCE CRYPTO NEWS BOT"
    )

    print(
        "======================================"
    )


    if not GEMINI_API_KEY:

        print("❌ GEMINI_API_KEY 없음")
        return


    if not TELEGRAM_TOKEN:

        print("❌ TELEGRAM_TOKEN 없음")
        return


    if not TELEGRAM_CHAT_ID:

        print("❌ TELEGRAM_CHAT_ID 없음")
        return


    sent_items = load_sent_items()

    now = datetime.now(
        timezone.utc
    )

    all_entries = fetch_all_entries()


    print(
        f"\n📦 전체 후보: "
        f"{len(all_entries)}개"
    )

    print(
        f"📚 기존 중복 기록: "
        f"{len(sent_items)}개"
    )


    all_entries.sort(
        key=lambda x: x["published"]
    )


    new_entries = []

    current_urls = set()

    current_guids = set()

    current_titles = []


    for item in all_entries:

        age = (
            now
            - item["published"]
        )


        if age.total_seconds() < -300:
            continue


        if age > timedelta(
            hours=MAX_ARTICLE_AGE_HOURS
        ):

            print(
                "⏭️ 오래된 기사 제외:",
                item["published"].isoformat(),
                item["title"]
            )

            continue


        feed_url = item["feed_url"]

        guid_key = item["guid_key"]

        title_key = item["title_key"]


        if (
            feed_url
            and feed_url in sent_items
        ):

            print(
                "⏭️ URL 중복:",
                item["title"]
            )

            continue


        if (
            guid_key
            and guid_key in sent_items
        ):

            print(
                "⏭️ GUID 중복:",
                item["title"]
            )

            continue


        if (
            title_key
            and title_key in sent_items
        ):

            print(
                "⏭️ 제목 중복:",
                item["title"]
            )

            continue


        if (
            feed_url
            and feed_url in current_urls
        ):
            continue


        if (
            guid_key
            and guid_key in current_guids
        ):
            continue


        if any(
            titles_are_same(
                item["title"],
                old
            )
            for old in current_titles
        ):

            print(
                "⏭️ 다른 소스 동일/유사 뉴스:",
                item["title"]
            )

            continue


        final_url = resolve_url(
            feed_url
        )


        if (
            final_url
            and final_url in sent_items
        ):

            print(
                "⏭️ 최종 URL 중복:",
                item["title"]
            )

            continue


        if (
            final_url
            and final_url in current_urls
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


        if guid_key:
            current_guids.add(
                guid_key
            )


        current_titles.append(
            item["title"]
        )


    if not new_entries:

        print(
            "\n✅ 새로 보낼 뉴스가 없습니다."
        )

        return


    print(
        f"\n🔥 새 뉴스 "
        f"{len(new_entries)}개 전송 시작"
    )


    client = genai.Client(
        api_key=GEMINI_API_KEY
    )


    success_count = 0
    fail_count = 0


    for index, item in enumerate(
        new_entries,
        1
    ):

        title = item["title"]


        summary = re.sub(
            r"<[^>]+>",
            " ",
            item["summary"]
        )


        summary = re.sub(
            r"\s+",
            " ",
            summary
        ).strip()


        source = item["source"]

        link = item["final_url"]


        print(
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        print(
            f"📰 {index}/"
            f"{len(new_entries)} | "
            f"{source}"
        )

        print(
            "제목:",
            title
        )

        print(
            "발행:",
            item["published"].isoformat()
        )

        print(
            "링크:",
            link
        )


        # =====================================================
        # 기사마다 길이를 조금씩 다르게
        # =====================================================

        style_roll = random.random()


        if style_roll < 0.15:

            length_guide = (
                "이번 기사는 비교적 짧게 정리한다. "
                "제목을 제외한 전체 내용이 모바일 화면 기준 "
                "대략 5줄 안팎이 되도록 한다. "
                "다만 줄 수를 억지로 정확하게 맞추지는 않는다."
            )

        else:

            target_lines = random.randint(
                7,
                10
            )

            length_guide = (
                f"이번 기사는 제목을 제외하고 모바일 화면 기준 "
                f"대략 {target_lines}줄 안팎으로 정리한다. "
                "기사 정보량에 따라 한두 줄 정도 차이가 나도 괜찮다. "
                "분량을 맞추기 위해 같은 내용을 반복하지 않는다."
            )


        # =====================================================
        # ★ 사람처럼 작성하도록 개선된 요약 프롬프트
        # =====================================================

        prompt = f"""
너는 암호화폐·금융 뉴스를 직접 읽고 텔레그램 뉴스 채널에 정리해서 올리는 사람이다.

아래 기사 제목과 RSS 내용을 충분히 이해한 다음,
단순히 문장을 짧게 줄이거나 원문의 표현을 바꿔 쓰는 방식이 아니라
실제로 사람이 기사를 읽고 중요한 내용을 골라 자기 말로 다시 설명하듯 작성한다.

독자가 원문을 읽지 않아도
'무슨 일이 있었는지, 무엇이 중요한지' 자연스럽게 이해할 수 있어야 한다.


[이번 기사 분량]

{length_guide}


[작성 방식]

- 인사말 없이 바로 기사 제목부터 시작한다.
- 첫 줄에는 기사 핵심을 담은 자연스러운 제목을 작성한다.
- 원문 제목을 반드시 그대로 복사할 필요는 없다.
- 다만 원래 기사의 의미를 바꾸거나 과장해서는 안 된다.

- 제목 다음에는 가장 중요한 내용부터 자연스럽게 설명한다.
- 기사의 문장 순서를 그대로 따라가지 말고, 사람이 읽고 이해한 순서대로 다시 정리한다.
- 단순 번역문이나 보도자료를 줄여놓은 것처럼 쓰지 않는다.

- '누가 무엇을 했다 → 그래서 어떤 상황인지 → 기사에서 중요하게 볼 내용이 무엇인지'
  정도의 흐름을 자연스럽게 만들되 모든 기사에 똑같은 구조를 강제로 적용하지 않는다.

- 짧은 기사는 짧고 간결하게 끝낸다.
- 설명이 필요한 기사라면 조금 더 풀어서 작성한다.
- 기사마다 문장 수와 문단 수가 달라도 된다.
- 문단 길이를 일부러 똑같이 맞추지 않는다.

- 한 문장에 너무 많은 정보를 집어넣지 않는다.
- 짧은 문장과 조금 긴 문장을 자연스럽게 섞는다.
- 문장 사이의 연결이 끊기는 느낌이 들지 않게 한다.

- '~했습니다. ~했습니다. ~했습니다.'처럼 같은 종결어미를 연속해서 반복하지 않는다.
- '~것으로 나타났습니다', '~것으로 분석됩니다', '~귀추가 주목됩니다'처럼
  AI 뉴스 요약에서 자주 나오는 상투적인 표현을 습관적으로 사용하지 않는다.

- 필요하다면
  '~했는데요',
  '~라는 내용입니다',
  '~로 보고 있습니다',
  '~이 부분이 눈에 띕니다',
  '~에 관심이 이어지고 있습니다'
  같은 자연스러운 연결 표현을 사용할 수 있다.
  하지만 이런 표현도 기사마다 반복하지 않는다.

- 지나치게 친근한 말투나 반말은 사용하지 않는다.
- 너무 딱딱한 보고서체도 사용하지 않는다.
- 뉴스 채널 운영자가 기사를 직접 읽고 구독자에게 설명해주는 정도의 자연스러운 존댓말을 사용한다.

- 기사마다 시작 문장과 연결 방식이 조금씩 달라야 한다.
- 모든 기사를 같은 템플릿에 넣은 것처럼 작성하지 않는다.

- 원문에 중요한 숫자, 날짜, 코인명, 기업명, 기관명, 인물명이 있으면 유지한다.
- 전문용어는 의미를 훼손하지 않는 범위에서 일반 독자가 이해하기 쉽게 표현한다.

- 중요하지 않은 배경 설명이나 같은 의미의 반복 문장은 과감히 제외한다.
- RSS 내용이 짧다면 없는 내용을 만들어 분량을 늘리지 않는다.


[사람이 쓴 글처럼 보이게 하는 핵심 원칙]

아래처럼 기계적으로 사실을 하나씩 나열하지 않는다.

나쁜 예:
"비트코인이 상승했습니다. 거래량도 증가했습니다. 시장의 관심이 높아졌습니다."

사람이 정리한 느낌:
"비트코인이 다시 상승세를 보이고 있습니다. 가격이 움직이면서 거래량도 함께 늘었고, 시장의 관심 역시 다시 커지는 모습입니다."

위 예문의 표현을 그대로 따라 쓰라는 뜻은 아니다.
기사 내용에 맞춰 매번 가장 자연스러운 문장 흐름을 새로 만든다.

또한 모든 기사에서
'요약하자면', '결론적으로', '핵심은'
같은 표현을 반복하지 않는다.


[사실성 규칙]

- 기사 제목과 RSS 요약에 실제로 제공된 정보만 사용한다.
- 기사에 없는 사실을 추가하지 않는다.
- 기사에 없는 원인이나 배경을 추측하지 않는다.
- 없는 숫자나 발언을 만들어내지 않는다.
- 기사 내용보다 확정적인 표현을 사용하지 않는다.
- 영어 기사는 자연스러운 한국어로 번역하면서 의미를 정확히 유지한다.

- 연준, SEC, 정부, 규제, 정책 관련 내용은 특히 사실 중심으로 중립적으로 작성한다.
- 정치적 평가나 개인적인 의견을 추가하지 않는다.

- 투자 권유를 하지 않는다.
- 기사에 없는 가격 전망을 추가하지 않는다.


[본문 디자인]

- 모바일 텔레그램에서 읽기 편하도록 적절히 문단을 나눈다.
- 한 문단을 지나치게 길게 만들지 않는다.
- 그렇다고 문장마다 무조건 줄바꿈하지 않는다.
- 기사마다 문단 수를 똑같이 맞추지 않는다.

- 번호 목록을 사용하지 않는다.
- 불릿 목록을 사용하지 않는다.
- 본문에 이모티콘이나 이모지를 사용하지 않는다.
- '핵심 포인트', '기사 요약', '한줄 요약', '결론', '정리' 같은 항목명을 만들지 않는다.


[마지막 부분]

본문 마지막에는 이 기사에서 독자가 기억할 만한 핵심 의미를
보통 1문장, 필요한 경우 2문장 정도로 자연스럽게 마무리한다.

마지막 문장은 앞에서 했던 말을 그대로 반복해서는 안 된다.

'요약하자면',
'짧게 말씀드리면',
'한 줄로 말씀드리면',
'핵심만 말씀드리면',
'결론적으로 보면'
같은 정형화된 머리말을 붙이지 않는다.

별도의 '요약:' 또는 '핵심:' 라벨도 사용하지 않는다.

사람이 글을 마무리하면서 마지막으로 중요한 내용을 짚어주는 느낌으로 작성한다.

기사에 없는 전망이나 개인적인 의견을 넣어 억지로 결론을 만들지 않는다.


[링크 관련]

- URL은 절대로 작성하지 않는다.
- '기사 원문 보러가기'라는 문구도 작성하지 않는다.
- 링크는 Python 프로그램이 본문 아래에 별도로 추가한다.


[출처]
{source}

[기사 제목]
{title}

[RSS 요약]
{summary[:3500]}
"""


        try:

            print(
                "🤖 Gemini 요약 생성 중..."
            )


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

                print(
                    "❌ Gemini 응답 없음"
                )

                fail_count += 1

                continue


            text = clean_gemini_text(
                result.text
            )


            if not text:

                print(
                    "❌ Gemini 요약 없음"
                )

                fail_count += 1

                continue


            # =================================================
            # 사이트 도메인을 기사 링크로 표시
            #
            # 예:
            # coindesk.com
            # bloomingbit.io
            # blockmedia.co.kr
            #
            # 표시된 도메인을 누르면 실제 기사로 이동
            # =================================================

            domain = get_site_domain(
                link
            )

            safe_link = escape_markdown_url(
                link
            )

            text += (
                f"\n\n"
                f"[{domain}]({safe_link})"
            )


            if not send_telegram(
                text
            ):

                print(
                    "❌ Telegram 전송 실패"
                )

                fail_count += 1

                continue


            keys = [

                item["feed_url"],

                item["final_url"],

                item["guid_key"],

                item["title_key"],
            ]


            save_sent_items(
                keys
            )


            for key in keys:

                if key:

                    sent_items.add(
                        key
                    )


            print(
                "✅ Telegram 전송 성공 / "
                "중복 기록 저장"
            )


            success_count += 1


        except Exception as e:

            print(
                "❌ 기사 처리 오류:",
                e
            )

            traceback.print_exc()

            fail_count += 1

            continue


    print(
        "\n======================================"
    )

    print(
        "🏁 실행 완료"
    )

    print(
        f"✅ 성공: "
        f"{success_count}개"
    )

    print(
        f"❌ 실패: "
        f"{fail_count}개"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
