"""
Demo seed script — populates MongoDB with the Kai demo scenario.
Run once before the demo: python scripts/seed_demo.py
"""
import asyncio
from datetime import date, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "daypilot")
USER_ID = "demo_user"


def in_days(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


async def seed():
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DB_NAME]

    # ── Clear existing demo data ──────────────────────────────────────────
    await db["entities"].delete_many({"user_id": USER_ID})
    await db["user_preferences"].delete_many({"user_id": USER_ID})
    await db["goal_state"].delete_many({"user_id": USER_ID})

    # ── Entities ──────────────────────────────────────────────────────────
    entities = [
        {
            "user_id": USER_ID,
            "entity_name": "Mia",
            "entity_type": "person",
            "relations": [
                {
                    "type": "partner",
                    "since": in_days(-90),
                    "upcoming_dates": [
                        {"event": "3-month anniversary with Mia", "date": in_days(8)}
                    ],
                }
            ],
            "social_priority_score": 0.95,
        },
        {
            "user_id": USER_ID,
            "entity_name": "Favorite Artist",
            "entity_type": "interest",
            "relations": [
                {
                    "type": "fan",
                    "upcoming_dates": [
                        {"event": "Favorite artist concert tickets go on sale", "date": in_days(3)}
                    ],
                }
            ],
            "social_priority_score": 0.7,
        },
        {
            "user_id": USER_ID,
            "entity_name": "ML Class",
            "entity_type": "event",
            "relations": [
                {
                    "type": "recurring_class",
                    "upcoming_dates": [
                        {"event": "ML class 2PM-4PM at library", "date": date.today().isoformat()}
                    ],
                }
            ],
            "social_priority_score": 0.0,
        },
    ]
    await db["entities"].insert_many(entities)

    # ── User preferences ──────────────────────────────────────────────────
    await db["user_preferences"].insert_one({
        "user_id": USER_ID,
        "focus_window": "9PM-1AM",
        "cognitive_style": "deep work at night, routine tasks in morning",
        "energy_pattern": "low morning, peak evening",
        "sleep_duration_hours": 7.0,
        "sleep_quality": "good",
        "user_reported_energy": "medium",
        "previous_workload": "moderate",
        "home_address": "USC Campus, Los Angeles",
        "task_preferences": {
            "avg_leetcode_duration_min": 45,
            "preferred_break_length_min": 10,
        },
        "commute": {
            "library_from_home_min": 30,
        },
    })

    # ── Goal state ────────────────────────────────────────────────────────
    await db["goal_state"].insert_one({
        "user_id": USER_ID,
        "goals": [
            {
                "goal": "Complete 10 Leetcode problems this week",
                "progress": 6,
                "target": 10,
                "deadline": in_days(4),
                "urgency": "medium",
                "suggested_blocks": ["2h Leetcode session tonight 9PM-11PM"],
            }
        ],
    })

    client.close()
    print(f"Seed complete. Database: {DB_NAME}, User: {USER_ID}")
    print(f"  - {len(entities)} entities inserted")
    print(f"  - user_preferences inserted")
    print(f"  - goal_state inserted (Leetcode 6/10, due {in_days(4)})")


if __name__ == "__main__":
    asyncio.run(seed())
