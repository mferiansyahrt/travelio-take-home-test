"""C2: count of messages per intent, per day, for the last 7 days, sorted by day.

Assumptions
- A "day" is a calendar day in Asia/Jakarta. created_at is stored in UTC.
- "Last 7 days" = today plus the previous 6 days. The start is computed in Python, so $match is a plain
  range on created_at and can use an index on created_at.
- Messages without an intent are counted as "unclassified".
- Days with no messages produce no rows.

Run: MONGO_URI="mongodb://localhost:27017" MONGO_DB="travelio" python c2_messages_per_intent_per_day.py
"""
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from pymongo import MongoClient

TIMEZONE = "Asia/Jakarta"


def build_pipeline(now: datetime | None = None) -> list[dict]:
    tz = ZoneInfo(TIMEZONE)
    now = (now or datetime.now(tz)).astimezone(tz)
    start_of_today = datetime.combine(now.date(), time.min, tzinfo=tz)
    since = start_of_today - timedelta(days=6)

    return [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {
            "_id": {
                "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": TIMEZONE}},
                "intent": {"$ifNull": ["$intent", "unclassified"]},
            },
            "count": {"$sum": 1},
        }},
        {"$project": {"_id": 0, "day": "$_id.day", "intent": "$_id.intent", "count": 1}},
        {"$sort": {"day": 1, "intent": 1}},
    ]


def main() -> None:
    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    messages = client[os.getenv("MONGO_DB", "travelio")]["messages"]
    for row in messages.aggregate(build_pipeline()):
        print(row)  # {'count': 41, 'day': '2026-09-09', 'intent': 'booking_inquiry'}


if __name__ == "__main__":
    main()
