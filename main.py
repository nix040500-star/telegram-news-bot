from datetime import datetime, timezone, timedelta
import email.utils

# 최신순으로 정렬
entries = sorted(
    feed.entries,
    key=lambda x: email.utils.parsedate_to_datetime(x.published)
    if getattr(x, "published", None)
    else datetime.min.replace(tzinfo=timezone.utc),
    reverse=True
)

# 최근 1시간 이내 기사만 선택
now = datetime.now(timezone.utc)
target_entry = None

for entry in entries:
    if not getattr(entry, "published", None):
        continue

    published = email.utils.parsedate_to_datetime(entry.published)

    if now - published <= timedelta(hours=1):
        target_entry = entry
        break

if target_entry is None:
    print("최근 1시간 이내 새 뉴스가 없습니다.")
    return

title = target_entry.title
link = target_entry.link
