"""
Seed today's located events for demo_user (INPUT only — not a pre-built schedule).

This writes calendar events into the `entities` knowledge graph with today's
date, each with a clear address. At demo time, the user types "plan my day" and
the coordinator reads these as today's events (days_away: 0), passes them to
plan_schedule as calendar_events with locations, and the AI generates a fresh
schedule with commute blocks + geo Navigate. Nothing here is a pre-generated
schedule — the plan is produced live by the AI.

Run before the demo: python scripts/seed_geo_events.py
"""
import asyncio
from datetime import date
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "daypilot")
USER_ID = "demo_user"
HOME = "900 Wilshire Blvd, Los Angeles, CA 90017"

# Today's located events. Phrased so the AI can parse time + full address.
EVENTS = [
    ("Doctor Appointment",
     "Doctor appointment from 8:30am to 9:30am at Keck Hospital of USC, 1500 San Pablo St, Los Angeles, CA 90033"),
    ("Career Workshop",
     "Career workshop from 10:30am to 12:00pm at Olin Hall of Engineering, 3650 McClintock Ave, Los Angeles, CA 90089"),
    ("Study Session",
     "Study session from 1:30pm to 3:30pm at Leavey Library, 650 W 35th St, Los Angeles, CA 90089"),
]


async def seed():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DB_NAME]
    today = date.today().isoformat()

    # Ensure home_address is set so geo origin resolves
    await db["user_preferences"].update_one(
        {"user_id": USER_ID},
        {"$set": {"home_address": HOME}},
        upsert=True,
    )

    # Remove any prior geo-demo event entities (idempotent re-runs)
    await db["entities"].delete_many(
        {"user_id": USER_ID, "entity_type": "geo_demo_event"}
    )

    docs = [
        {
            "user_id": USER_ID,
            "entity_name": name,
            "entity_type": "geo_demo_event",
            "relations": [
                {
                    "type": "calendar_event",
                    "upcoming_dates": [{"event": text, "date": today}],
                }
            ],
            "social_priority_score": 0.0,
        }
        for (name, text) in EVENTS
    ]
    await db["entities"].insert_many(docs)
    print(f"Seeded {len(docs)} located events for {USER_ID} on {today}")
    print("Now: in the frontend (user_id=demo_user), send 'plan my day' to generate live.")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
