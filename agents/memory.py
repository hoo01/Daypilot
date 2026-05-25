from datetime import datetime, timedelta
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from schemas import Entity, UpcomingEvent
from db import Collections


class MemoryAgent:
    """
    Single source of truth for the Knowledge Graph.
    No agent writes to MongoDB directly — all DB access goes through here.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self._db = db

    async def write_entity(self, entity: Entity) -> None:
        entity.updated_at = datetime.utcnow()
        await self._db[Collections.ENTITIES].update_one(
            {"user_id": entity.user_id, "entity_name": entity.entity_name},
            {"$set": entity.model_dump()},
            upsert=True,
        )

    async def read_entity(self, user_id: str, name: str) -> Entity | None:
        doc = await self._db[Collections.ENTITIES].find_one(
            {"user_id": user_id, "entity_name": name}
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return Entity(**doc)

    async def query_upcoming(self, user_id: str, days: int = 14) -> list[UpcomingEvent]:
        """Return all upcoming_dates within the next `days` days across all entities."""
        cutoff = (datetime.utcnow() + timedelta(days=days)).date().isoformat()
        today = datetime.utcnow().date().isoformat()

        cursor = self._db[Collections.ENTITIES].find({"user_id": user_id})
        upcoming: list[UpcomingEvent] = []
        async for doc in cursor:
            for relation in doc.get("relations", []):
                for ud in relation.get("upcoming_dates", []):
                    if today <= ud["date"] <= cutoff:
                        upcoming.append(UpcomingEvent(**ud))
        return upcoming

    async def update_preference(self, user_id: str, key: str, value: Any) -> None:
        await self._db[Collections.USER_PREFERENCES].update_one(
            {"user_id": user_id},
            {"$set": {key: value}},
            upsert=True,
        )

    async def get_preferences(self, user_id: str) -> dict:
        doc = await self._db[Collections.USER_PREFERENCES].find_one({"user_id": user_id})
        if doc:
            doc.pop("_id", None)
        return doc or {}

    async def upsert_goal_state(self, user_id: str, goal_data: dict) -> None:
        await self._db[Collections.GOAL_STATE].update_one(
            {"user_id": user_id},
            {"$set": goal_data},
            upsert=True,
        )

    async def get_goal_state(self, user_id: str) -> dict:
        doc = await self._db[Collections.GOAL_STATE].find_one({"user_id": user_id})
        if doc:
            doc.pop("_id", None)
        return doc or {}
