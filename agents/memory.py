import asyncio
from datetime import datetime, timedelta
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from google import genai

from schemas import Entity, UpcomingEvent
from db import Collections
from config import settings

_genai_client = genai.Client(api_key=settings.gemini_api_key)


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

    async def cache_today_calendar_events(self, user_id: str, date_str: str, events: list[dict]) -> None:
        """Cache today's real Google Calendar events (wall-clock times) for quick lookup."""
        await self._db[Collections.CALENDAR_CACHE].update_one(
            {"user_id": user_id, "date": date_str},
            {"$set": {"events": events, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    async def get_today_calendar_events(self, user_id: str) -> list[dict]:
        """Return today's cached Google Calendar events, if any."""
        today_str = datetime.now().date().isoformat()
        doc = await self._db[Collections.CALENDAR_CACHE].find_one({"user_id": user_id, "date": today_str})
        return doc.get("events", []) if doc else []

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

    async def store_memory(self, user_id: str, text: str, metadata: dict | None = None) -> None:
        """Embed text and store in conversation_memory for later semantic retrieval."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _genai_client.models.embed_content(model="models/gemini-embedding-001", contents=text),
        )
        embedding = result.embeddings[0].values
        await self._db[Collections.CONVERSATION_MEMORY].insert_one({
            "user_id": user_id,
            "text": text,
            "embedding": embedding,
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
        })

    async def retrieve_similar(self, user_id: str, query: str, k: int = 3) -> list[dict]:
        """Find the k most semantically similar memories for a given query."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _genai_client.models.embed_content(model="models/gemini-embedding-001", contents=query),
        )
        query_embedding = result.embeddings[0].values
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "conversation_memory_vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": k * 10,
                    "limit": k,
                    "filter": {"user_id": user_id},
                }
            },
            {"$project": {"_id": 0, "text": 1, "metadata": 1, "created_at": 1}},
        ]
        cursor = self._db[Collections.CONVERSATION_MEMORY].aggregate(pipeline)
        return [doc async for doc in cursor]
