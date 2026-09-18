[main.py]
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
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SENT_FILE = "sent_urls.txt"
LOOKBACK_MINUTES = 30

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

BLOOMINGBIT_SEARCH_URL = "https://bloomingbit.io/search"


def fetch_bloomingbit_entries():
    """블루밍비트 검색/최신 페이지에서 기사 링크를 직접 수집한다."""
    print("\n🔎 Bloomingbit 확인 중...")
    collected = []

    try:
        r = requests.get(BLOOMINGBIT_SEARCH_URL, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"❌ Bloomingbit HTTP {r.status_code}")
            return collected

        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()

        for a in soup.select('a[href*="/feed/news/"]'):
            href = (a.get("href") or "").strip()
            title = a.get_text(" ", strip=True)

            if not href:
                continue

            url = urllib.parse.urljoin("https://bloomingbit.io", href)
            url = canonicalize_url(url)

            if url in seen:
                continue
            seen.add(url)

            # 목록에서 제목이 비어 있으면 기사 페이지에서 직접 가져온다.
            try:
                article = requests.get(url, headers=HEADERS, timeout=15)
                if article.status_code != 200:
                    continue

                article_soup = BeautifulSoup(article.text, "html.parser")

                if not title:
                    h1 = article_soup.find("h1")
                    if h1:
                        title = h1.get_text(" ", strip=True)

                # og:title fallback
                if not title:
                    og_title = article_soup.find("meta", property="og:title")
                    if og_title:
                        title = (og_title.get("content") or "").strip()

                # published_time / datePublished 탐색
                published = None
                for meta_key, meta_value in [
                    ("property", "article:published_time"),
                    ("name", "article:published_time"),
                    ("itemprop", "datePublished"),
                ]:
                    tag = article_soup.find("meta", attrs={meta_key: meta_value})
                    if tag and tag.get("content"):
                        raw = tag.get("content").strip()
                        try:
                            published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                            if published.tzinfo is None:
                                published = published.replace(tzinfo=timezone.utc)
                            published = published.astimezone(timezone.utc)
                            break
                        except Exception:
                            pass

                # JSON-LD fallback
                if published is None:
                    for script in article_soup.find_all("script", type="application/ld+json"):
                        raw = script.string or script.get_text()
                        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw or "")
                        if m:
                            try:
                                published = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
                                if published.tzinfo is None:
                                    published = published.replace(tzinfo=timezone.utc)
                                published = published.astimezone(timezone.utc)
                                break
                            except Exception:
                                pass

                if not title or published is None:
                    continue

                desc = ""
                meta_desc = article_soup.find("meta", attrs={"name": "description"})
                if meta_desc:
                    desc = (meta_desc.get("content") or "").strip()

                collected.append({
                    "source": "Bloomingbit",
                    "feed_type": "crypto",
                    "entry": {"title": title, "link": url, "id": url},
                    "title": title,
                    "summary": desc,
                    "feed_url": url,
                    "published": published,
                    "guid_key": "GUID:" + url,
                    "title_key": make_title_key(title),
                })

            except Exception as e:
                print("⚠️ Bloomingbit 기사 확인 실패:", e)
                continue

        print(f"📰 Bloomingbit: {len(collected)}개")
        return collected

    except Exception as e:
        print("❌ Bloomingbit 수집 오류:", e)
        return collected


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

    ratio = SequenceMatcher(None, a, b).ratio()
    if ratio >= 0.90:
        return True

    aw = set(a.split())
    bw = set(b.split())
    if not aw or not bw:
        return False
    overlap = len(aw & bw) / max(1, min(len(aw), len(bw)))
    return overlap >= 0.88 and min(len(aw), len(bw)) >= 5


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

    # 블루밍비트는 RSS 대신 웹 최신/검색 페이지를 직접 확인
    collected.extend(fetch_bloomingbit_entries())

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
        age = now - item["published"]

        if age.total_seconds() < -300:
            continue
        if age > timedelta(minutes=LOOKBACK_MINUTES):
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
        if normalize_title(item["title"]) in {
            normalize_title(old) for old in current_titles
        }:
            print("⏭️ 다른 소스 동일 제목 기사:", item["title"])
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

        prompt = f"""
너는 암호화폐·금융 뉴스 전문 요약 에디터다.

아래 RSS 기사 정보를 한국어로 요약한다.

[규칙]
- 인사말 없이 바로 시작한다.
- 모바일 텔레그램에서 빠르게 읽을 수 있도록 짧은 2문단으로 작성한다.
- 기사 제목과 RSS 요약에 실제로 들어있는 정보만 사용한다.
- 없는 사실, 수치, 인용, 배경을 만들지 않는다.
- 영어 기사도 자연스러운 한국어로 번역·요약한다.
- 전문용어는 쉽게 풀어쓴다.
- 같은 내용을 반복하지 않는다.
- 투자 권유나 가격 예측을 하지 않는다.
- 코인명, 기업명, 인물명, 중요한 수치는 유지한다.
- 연준·SEC·정부·정책 관련 내용은 사실 중심으로 중립적으로 작성한다.
- URL은 절대로 작성하지 않는다.
- '기사 원문 보러가기' 문구도 작성하지 않는다.

마지막에는 기사 전체 핵심을 한 문장으로 요약한다.
단, 마지막 핵심 문장 앞에 '짧게 말씀드리면', '요약하자면', '핵심은', '그래서 무슨 말이냐면', '쉽게 말하면' 같은 머리말은 직접 작성하지 않는다.
머리말은 Python 프로그램이 랜덤으로 추가한다.

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
                "📌 짧게 말씀드리면..",
                "📌 요약하자면..",
                "📌 핵심은..",
                "📌 그래서 무슨 말이냐면..",
                "📌 쉽게 말하면..",
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


================================================================================
[.github/workflows/news.yml]
================================================================================

name: Crypto News Bot

on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: crypto-news-bot
  cancel-in-progress: false

jobs:
  crypto-news:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests feedparser google-genai beautifulsoup4

      - name: Sync repository
        run: |
          git pull --rebase origin "${{ github.ref_name }}"

      - name: Run crypto news bot
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          python main.py

      - name: Save sent news history
        if: always()
        run: |
          if [ ! -f sent_urls.txt ]; then
            echo "sent_urls.txt 없음"
            exit 0
          fi

          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add sent_urls.txt

          if git diff --cached --quiet; then
            echo "새로운 전송 기록 없음"
            exit 0
          fi

          git commit -m "Update sent crypto news history"
          git pull --rebase origin "${{ github.ref_name }}"
          git push origin HEAD:"${{ github.ref_name }}"

