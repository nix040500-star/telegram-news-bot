import os
import re
import hashlib
import random
import base64
import traceback
import requests
import feedparser
import urllib.parse
import email.utils
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from google import genai

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SENT_FILE = "sent_urls.txt"
MAX_ARTICLE_AGE_HOURS = 1

PROMO_KST_HOURS = {0, 6, 12, 18}
PROMO_STATE_PREFIX = "PROMO_SLOT:"
TRON_GUIDE_STATE_PREFIX = "TRON_GUIDE_SLOT:"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMO_IMAGE_PATH = os.path.join(BASE_DIR, "지갑보안검사 메뉴얼.png")
TRON_GUIDE_IMAGE_PATH = os.path.join(BASE_DIR, "트론 충전 메뉴얼.png")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    )
}

CRYPTO_TERMS = [
    "crypto", "cryptocurrency", "bitcoin", "btc", "ethereum", "eth",
    "xrp", "ripple", "dogecoin", "doge", "stablecoin", "usdt",
    "tether", "coinbase", "binance", "blockchain", "digital asset",
    "token", "코인", "암호화폐", "가상자산", "비트코인", "이더리움",
    "리플", "도지코인", "도지", "스테이블코인"
]

MACRO_TERMS = [
    "federal reserve", "fed", "fomc", "powell", "interest rate",
    "rate hike", "rate cut", "inflation", "sec", "etf",
    "연준", "파월", "금리", "인플레이션"
]

GOOGLE_QUERY = (
    '("코인" OR "암호화폐" OR "가상자산" OR "비트코인" OR BTC OR '
    '"이더리움" OR ETH OR "리플" OR XRP OR "도지코인" OR DOGE OR '
    '"스테이블코인" OR USDT OR ETF OR SEC OR "연준" OR Fed OR '
    'FOMC OR "연준 의장" OR "금리" OR "파월") when:1d'
)

google_rss = (
    "https://news.google.com/rss/search?"
    f"q={urllib.parse.quote(GOOGLE_QUERY)}"
    "&hl=ko&gl=KR&ceid=KR:ko"
)

FEEDS = [
    ("Google News KR", google_rss, "google"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    ("Cointelegraph", "https://cointelegraph.com/rss", "crypto"),
    ("Decrypt", "https://decrypt.co/feed", "crypto"),
    ("Federal Reserve - Monetary Policy", "https://www.federalreserve.gov/feeds/press_monetary.xml", "macro"),
    ("Federal Reserve - Speeches", "https://www.federalreserve.gov/feeds/speeches.xml", "macro"),
]


def load_sent_items():
    if not os.path.exists(SENT_FILE):
        return set()
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception as e:
        print("⚠️ 전송 기록 읽기 실패:", e)
        return set()


def save_sent_items(items):
    items = [x.strip() for x in items if x and x.strip()]
    if not items:
        return
    with open(SENT_FILE, "a", encoding="utf-8") as f:
        for item in items:
            f.write(item + "\n")


def strip_source_suffix(title):
    title = (title or "").strip()
    # Google News often appends publisher name after " - "
    parts = re.split(r"\s+-\s+", title)
    if len(parts) > 1 and len(parts[-1]) <= 40:
        title = " - ".join(parts[:-1])
    return title.strip()


def normalize_title(title):
    title = strip_source_suffix(title).lower()
    title = re.sub(r"https?://\S+", "", title)
    title = re.sub(r"[^가-힣a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def make_title_key(title):
    normalized = normalize_title(title)
    if not normalized:
        return ""
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return "TITLE:" + digest


def make_guid_key(entry):
    guid = entry.get("id") or entry.get("guid") or ""
    guid = str(guid).strip()
    return "GUID:" + guid if guid else ""


def canonicalize_url(url):
    if not url:
        return ""
    try:
        p = urllib.parse.urlsplit(url.strip())
        query = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        tracking = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "utm_id", "gclid", "fbclid", "mc_cid", "mc_eid"
        }
        query = [(k, v) for k, v in query if k.lower() not in tracking]
        clean_query = urllib.parse.urlencode(query, doseq=True)
        return urllib.parse.urlunsplit(
            (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), clean_query, "")
        )
    except Exception:
        return url.strip()


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

    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(
                    value.tm_year, value.tm_mon, value.tm_mday,
                    value.tm_hour, value.tm_min, value.tm_sec,
                    tzinfo=timezone.utc
                )
            except Exception:
                pass

    return None


def resolve_url(url):
    if not url:
        return ""
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=12,
            allow_redirects=True
        )
        final_url = canonicalize_url(r.url)
        if final_url.startswith("http"):
            return final_url
    except Exception as e:
        print("⚠️ URL 확인 실패:", e)
    return canonicalize_url(url)


def is_relevant(title, summary, feed_type):
    text = f"{title} {summary}".lower()

    if feed_type in ("crypto", "google"):
        return any(term.lower() in text for term in CRYPTO_TERMS + MACRO_TERMS)

    if feed_type == "macro":
        # Fed feed: only send crypto-relevant policy news or major monetary-policy items.
        crypto_hit = any(term.lower() in text for term in CRYPTO_TERMS)
        major_macro = any(
            term in text
            for term in [
                "fomc", "federal funds", "interest rate", "monetary policy",
                "powell", "inflation", "rate", "digital asset",
                "crypto", "stablecoin"
            ]
        )
        return crypto_hit or major_macro

    return True


def titles_are_same(a, b):
    a = normalize_title(a)
    b = normalize_title(b)
    if not a or not b:
        return False
    if a == b:
        return True

    # 다른 언론사가 같은 사건을 조금 다르게 쓴 경우까지 중복으로 판단
    if SequenceMatcher(None, a, b).ratio() >= 0.78:
        return True

    stopwords = {
        "및", "등", "관련", "대한", "통해", "위해", "에서", "으로",
        "한다", "발표", "전망", "가능성", "the", "a", "an", "to",
        "of", "in", "on", "for", "and", "with", "as", "is", "are",
        "says", "said"
    }
    aw = {x for x in a.split() if len(x) >= 2 and x not in stopwords}
    bw = {x for x in b.split() if len(x) >= 2 and x not in stopwords}
    if not aw or not bw:
        return False

    common = aw & bw
    overlap_small = len(common) / min(len(aw), len(bw))
    overlap_union = len(common) / len(aw | bw)

    return (
        (len(common) >= 3 and overlap_small >= 0.60)
        or (len(common) >= 4 and overlap_union >= 0.45)
    )


def clean_gemini_text(text):
    if not text:
        return ""
    text = text.strip()
    text = re.sub(
        r"\n*🔗\s*\[기사 원문 보러가기\]\([^)]+\)",
        "",
        text
    )
    text = re.sub(r"\n*https?://\S+\s*$", "", text)
    return text.strip()


def escape_markdown_url(url):
    return url.replace("(", "%28").replace(")", "%29")


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram 환경변수 없음")
        return False

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        r = requests.post(api_url, json=payload, timeout=30)
        print("📡 Telegram:", r.status_code)
        if r.status_code == 200:
            return True

        # Markdown special chars in AI output can occasionally break Telegram parsing.
        print("⚠️ Markdown 전송 실패, 일반 텍스트로 재시도:", r.text)
        payload.pop("parse_mode", None)
        r = requests.post(api_url, json=payload, timeout=30)
        print("📡 Telegram 재시도:", r.status_code)
        if r.status_code != 200:
            print("❌ Telegram 오류:", r.text)
            return False
        return True
    except Exception as e:
        print("❌ Telegram 요청 오류:", e)
        return False



def get_kst_promo_slot():
    """한국시간 00:00 / 06:00 / 12:00 / 18:00 슬롯을 반환한다."""
    now_kst = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    if now_kst.hour not in PROMO_KST_HOURS:
        return None
    # GitHub Actions 20분 주기 기준: 정각 실행(:00)만 이 구간에 들어온다.
    if now_kst.minute >= 20:
        return None
    return now_kst.strftime("%Y-%m-%d-%H")


def promo_slot_already_sent(prefix, slot):
    if not slot or not os.path.exists(SENT_FILE):
        return False
    marker = prefix + slot
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return any(line.strip() == marker for line in f)
    except Exception as e:
        print("⚠️ 홍보 슬롯 기록 읽기 실패:", e)
        return False


def save_promo_slot(prefix, slot):
    if not slot:
        return False
    marker = prefix + slot
    try:
        with open(SENT_FILE, "a", encoding="utf-8") as f:
            f.write(marker + "\n")
        return True
    except Exception as e:
        print("⚠️ 홍보 슬롯 기록 저장 실패:", e)
        return False


def send_usdt_scan_guard_promo():
    """한국시간 00시, 06시, 12시, 18시에 슬롯당 1회 게시한다."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram 환경변수 없음 - 홍보 게시 생략")
        return False

    slot = get_kst_promo_slot()
    if slot is None:
        return False
    if promo_slot_already_sent(PROMO_STATE_PREFIX, slot):
        return False

    if not os.path.exists(PROMO_IMAGE_PATH):
        print("❌ 이미지 없음:", PROMO_IMAGE_PATH)
        return False

    caption = """*USDT 스캔 가드(USDT SCAN GUARD)*

빠르고 안전한 디지털 자산 보안 관리

• *보안 점검:* 자산 및 주소 안전성 실시간 확인
• *위험 차단:* 잠재적 위협 요소 사전 예방
• *체계적 보호:* 믿을 수 있는 디지털 자산 관리

지갑의 위험을 미리 확인하고, 더 안전하게 보호하세요.

[지갑 안전검사](https://hig.kr/cryptoguard)"""

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        image_file = open(PROMO_IMAGE_PATH, "rb")
        r = requests.post(
            api_url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "Markdown",
            },
            files={"photo": ("지갑보안검사 메뉴얼.png", image_file, "image/png")},
            timeout=60,
        )
        image_file.close()
        print("📣 USDT SCAN GUARD 홍보:", r.status_code)
        if r.status_code != 200:
            print("❌ 홍보 게시 실패:", r.text)
            return False

        if save_promo_slot(PROMO_STATE_PREFIX, slot):
            print(f"✅ USDT SCAN GUARD 게시 완료: KST {slot}")
        return True
    except Exception as e:
        print("❌ USDT SCAN GUARD 홍보 게시 오류:", e)
        traceback.print_exc()
        return False


def send_tron_guide_promo():
    """한국시간 00시, 06시, 12시, 18시에 슬롯당 1회 게시한다."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    slot = get_kst_promo_slot()
    if slot is None:
        return False
    if promo_slot_already_sent(TRON_GUIDE_STATE_PREFIX, slot):
        return False

    if not os.path.exists(TRON_GUIDE_IMAGE_PATH):
        print("❌ 이미지 없음:", TRON_GUIDE_IMAGE_PATH)
        return False

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        image_file = open(TRON_GUIDE_IMAGE_PATH, "rb")
        r = requests.post(
            api_url,
            data={"chat_id": TELEGRAM_CHAT_ID},
            files={"photo": ("트론 충전 메뉴얼.png", image_file, "image/png")},
            timeout=60,
        )
        image_file.close()
        print("📘 TRON/USDT 안내 이미지:", r.status_code)
        if r.status_code != 200:
            print("❌ TRON/USDT 안내 이미지 게시 실패:", r.text)
            return False

        if save_promo_slot(TRON_GUIDE_STATE_PREFIX, slot):
            print(f"✅ TRON/USDT 안내 이미지 게시 완료: KST {slot}")
        return True
    except Exception as e:
        print("❌ TRON/USDT 안내 이미지 게시 오류:", e)
        traceback.print_exc()
        return False


def fetch_all_entries():
    collected = []

    for source, feed_url, feed_type in FEEDS:
        print(f"\n🔎 {source} 확인 중...")

        try:
            r = requests.get(feed_url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"❌ {source} HTTP {r.status_code}")
                continue

            feed = feedparser.parse(r.content)
            if getattr(feed, "bozo", False):
                print(f"⚠️ {source} RSS 경고:", getattr(feed, "bozo_exception", ""))

            entries = list(feed.entries or [])
            print(f"📰 {source}: {len(entries)}개")

            for entry in entries:
                title = str(entry.get("title", "")).strip()
                link = str(entry.get("link", "")).strip()
                summary = str(entry.get("summary", "") or entry.get("description", "")).strip()
                published = parse_date(entry)

                if not title or not link or not published:
                    continue

                if not is_relevant(title, summary, feed_type):
                    continue

                collected.append({
                    "source": source,
                    "feed_type": feed_type,
                    "entry": entry,
                    "title": title,
                    "summary": summary,
                    "feed_url": canonicalize_url(link),
                    "published": published,
                    "guid_key": make_guid_key(entry),
                    "title_key": make_title_key(title),
                })

        except Exception as e:
            print(f"❌ {source} 수집 오류:", e)
            continue

    return collected


def main():
    print("\n======================================")
    print("🚀 MULTI-SOURCE CRYPTO NEWS BOT")
    print("======================================")

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY 없음")
        return
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN 없음")
        return
    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID 없음")
        return

    # 뉴스 게시 여부와 관계없이 6시간 주기의 홍보 게시를 별도로 확인한다.
    send_usdt_scan_guard_promo()
    send_tron_guide_promo()

    sent_items = load_sent_items()
    now = datetime.now(timezone.utc)
    all_entries = fetch_all_entries()
    print(f"\n📦 전체 후보: {len(all_entries)}개")
    print(f"📚 기존 중복 기록: {len(sent_items)}개")

    all_entries.sort(key=lambda x: x["published"])

    new_entries = []
    current_urls = set()
    current_guids = set()
    current_titles = []

    for item in all_entries:
        # 오래된 미전송 기사가 갑자기 올라오는 것을 막는다.
        # RSS/Google News 표시시간 차이를 고려해 최근 1시간까지만 허용한다.
        age = now - item["published"]
        if age.total_seconds() < -300:
            continue
        if age > timedelta(hours=MAX_ARTICLE_AGE_HOURS):
            print("⏭️ 오래된 기사 제외:", item["published"].isoformat(), item["title"])
            continue

        feed_url = item["feed_url"]
        guid_key = item["guid_key"]
        title_key = item["title_key"]

        if feed_url and feed_url in sent_items:
            print("⏭️ URL 중복:", item["title"])
            continue
        if guid_key and guid_key in sent_items:
            print("⏭️ GUID 중복:", item["title"])
            continue
        if title_key and title_key in sent_items:
            print("⏭️ 제목 중복:", item["title"])
            continue

        if feed_url and feed_url in current_urls:
            continue
        if guid_key and guid_key in current_guids:
            continue
        if any(titles_are_same(item["title"], old) for old in current_titles):
            print("⏭️ 다른 소스 동일/유사 뉴스:", item["title"])
            continue

        # Resolve only after cheap duplicate checks.
        final_url = resolve_url(feed_url)
        if final_url and final_url in sent_items:
            print("⏭️ 최종 URL 중복:", item["title"])
            continue
        if final_url and final_url in current_urls:
            continue

        item["final_url"] = final_url or feed_url
        new_entries.append(item)

        if feed_url:
            current_urls.add(feed_url)
        if final_url:
            current_urls.add(final_url)
        if guid_key:
            current_guids.add(guid_key)
        current_titles.append(item["title"])

    if not new_entries:
        print("\n✅ 새로 보낼 뉴스가 없습니다.")
        return

    # 발견된 미전송 새 뉴스는 개수 제한 없이 전부 전송
    print(f"\n🔥 새 뉴스 {len(new_entries)}개 전송 시작")

    client = genai.Client(api_key=GEMINI_API_KEY)
    success_count = 0
    fail_count = 0

    for index, item in enumerate(new_entries, 1):
        title = item["title"]
        summary = re.sub(r"<[^>]+>", " ", item["summary"])
        summary = re.sub(r"\s+", " ", summary).strip()
        source = item["source"]
        link = item["final_url"]

        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"📰 {index}/{len(new_entries)} | {source}")
        print("제목:", title)
        print("발행:", item["published"].isoformat())
        print("링크:", link)

        # 기사마다 길이와 문단 구성을 랜덤하게 바꿔 반복적인 봇 느낌을 줄인다.
        style_roll = random.random()
        if style_roll < 0.15:
            length_guide = (
                "이번 기사는 아주 짧게 쓴다. 제목을 제외한 본문과 핵심 요약을 합쳐 대략 5줄 안팎으로 끝낸다. "
                "문단 수나 문장 수를 억지로 맞추지 않는다."
            )
        else:
            target_lines = random.randint(7, 10)
            length_guide = (
                f"이번 기사는 제목을 제외한 본문과 핵심 요약을 대략 {target_lines}줄 안팎으로 쓴다. "
                "정보량에 따라 한두 줄 차이는 괜찮으며 문단 수와 문장 수를 매번 똑같이 맞추지 않는다."
            )

        prompt = f"""
너는 암호화폐·금융 뉴스 전문 요약 에디터다.

아래 RSS 기사 정보를 한국어로 요약한다.

[작성 규칙]
- 인사말 없이 바로 시작한다.

[이번 기사 길이]
{length_guide}

- 제목 1줄 뒤에 본문과 마지막 핵심 요약을 작성한다.
- 매 기사마다 길이, 문장 수, 문단 수가 조금씩 달라야 한다. 항상 같은 틀로 맞추지 않는다.
- 어떤 기사는 한 문단이 길고 다른 문단이 짧아도 되며, 정보가 적으면 한 문단만 써도 된다.
- 아래 [이번 기사 길이] 지시를 우선 적용한다.
- 불필요한 배경 설명, 반복 표현, 장황한 설명은 제거한다.
- 기사 제목과 RSS 요약에 실제로 들어있는 정보만 사용한다.
- 없는 사실, 수치, 인용, 배경을 만들지 않는다.
- 영어 기사도 자연스러운 한국어로 번역·요약한다.
- 전문용어는 일반인이 이해하기 쉽게 풀어쓴다.
- 같은 내용을 반복하지 않는다.
- 투자 권유나 가격 예측을 하지 않는다.
- 코인명, 기업명, 인물명, 중요한 수치와 날짜는 유지한다.
- 연준·SEC·정부·정책 관련 내용은 사실 중심으로 중립적으로 작성한다.
- 딱딱한 AI 문체보다 사람이 뉴스를 직접 정리해 전달하는 자연스러운 문체를 사용한다.
- URL은 절대로 작성하지 않는다.
- '기사 원문 보러가기' 문구도 작성하지 않는다.

[마지막 핵심 요약]
- 본문 아래에 기사 전체 핵심을 보통 1~2줄로 짧고 자연스럽게 정리한다. 아주 짧은 기사에서는 1줄이면 충분하다.
- 마지막 핵심 문장에는 머리말을 직접 작성하지 않는다.
- '요약하자면', '짧게 말씀드리면', '한 줄로 말씀드리면', '두 줄로 짧게 말씀드리면',
  '쉽게 말씀드리면', '간단히 정리하면', '핵심만 말씀드리면', '결론적으로 보면',
  '지금 상황만 보면', '쉽게 풀어보면' 등의 머리말은 Python 프로그램이 매번 랜덤으로 추가한다.
- 핵심 문장은 사람이 직접 뉴스를 읽고 정리한 것처럼 자연스럽게 작성한다.

[출처]
{source}

[기사 제목]
{title}

[RSS 요약]
{summary[:3500]}
"""

        try:
            print("🤖 Gemini 요약 생성 중...")
            result = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )

            if not result or not getattr(result, "text", None):
                print("❌ Gemini 응답 없음")
                fail_count += 1
                continue

            text = clean_gemini_text(result.text)
            if not text:
                print("❌ Gemini 요약 없음")
                fail_count += 1
                continue

            closing_labels = [
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

            # Gemini의 마지막 비어있지 않은 줄을 핵심 한 문장으로 보고
            # Python에서 머리말을 랜덤으로 붙인다.
            lines = [line.rstrip() for line in text.splitlines()]
            nonempty = [i for i, line in enumerate(lines) if line.strip()]
            if nonempty:
                last_idx = nonempty[-1]
                last_line = lines[last_idx].strip()
                # 혹시 Gemini가 기존 머리말을 붙였으면 제거
                last_line = re.sub(
                    r"^(?:📌\s*)?(?:짧게\s*말씀드리면|요약하자면|핵심은|그래서\s*무슨\s*말이냐면|쉽게\s*말하면)\s*[.·:…-]*\s*",
                    "",
                    last_line,
                    flags=re.IGNORECASE,
                ).strip()
                lines[last_idx] = random.choice(closing_labels) + "\n" + last_line
                text = "\n".join(lines).strip()

            safe_link = escape_markdown_url(link)
            text += f"\n\n🔗 [기사 원문 보러가기]({safe_link})"

            if not send_telegram(text):
                print("❌ Telegram 전송 실패")
                fail_count += 1
                continue

            keys = [
                item["feed_url"],
                item["final_url"],
                item["guid_key"],
                item["title_key"],
            ]
            save_sent_items(keys)
            for key in keys:
                if key:
                    sent_items.add(key)

            print("✅ Telegram 전송 성공 / 중복 기록 저장")
            success_count += 1

        except Exception as e:
            print("❌ 기사 처리 오류:", e)
            traceback.print_exc()
            fail_count += 1
            continue

    print("\n======================================")
    print("🏁 실행 완료")
    print(f"✅ 성공: {success_count}개")
    print(f"❌ 실패: {fail_count}개")
    print("======================================")


if __name__ == "__main__":
    main()
