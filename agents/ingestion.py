import json
from agents.base import BaseAgent
from agents.memory import MemoryAgent
from schemas import Entity, EntityType, Relation
from config import settings


class IngestionAgent(BaseAgent):
    """
    Reads Google Calendar, Gmail metadata, Contacts, Spotify on cold start
    and on daily cron. Extracts entities + relations → writes via MemoryAgent.
    """

    model_name = settings.ingestion_model

    def __init__(self, memory: MemoryAgent):
        self.memory = memory

    async def run(self, input_data: dict) -> dict:
        """
        input_data keys:
          user_id      : str
          credentials  : google oauth token dict
          source       : "cold_start" | "incremental"
        """
        user_id = input_data["user_id"]
        source = input_data.get("source", "incremental")

        # TODO: call Google Calendar API, Gmail metadata API, Contacts API
        # raw_data = await self._fetch_google_data(input_data["credentials"])

        # TODO: call Gemini to extract entities from raw_data
        # entities = await self._extract_entities(user_id, raw_data)

        # TODO: write each entity via memory agent
        # for entity in entities:
        #     await self.memory.write_entity(entity)

        return {"status": "ok", "source": source, "entities_ingested": 0}

    async def _fetch_google_data(self, credentials: dict) -> dict:
        # TODO: implement Google API calls
        raise NotImplementedError

    async def _extract_entities(self, user_id: str, raw_data: dict) -> list[Entity]:
        prompt = f"""
You are an entity extractor. Given the following user data, extract all meaningful entities.
Return a JSON array of objects with fields: entity_name, entity_type, relations.
entity_type must be one of: person, goal, preference, event, interest.

Data:
{json.dumps(raw_data, indent=2)}

user_id: {user_id}
"""
        response_text = await self._generate(prompt)
        # TODO: parse and validate response_text into Entity objects
        raise NotImplementedError
