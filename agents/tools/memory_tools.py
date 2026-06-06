from db import get_db
from agents.memory import MemoryAgent
from telemetry.instrument import traced_tool

def _memory() -> MemoryAgent:
    return MemoryAgent(get_db())


@traced_tool("read_user_context")
async def read_user_context(user_id: str) -> dict:
    """Read user preferences, goals, and upcoming events from the Knowledge Graph."""
    mem = _memory()
    prefs = await mem.get_preferences(user_id)
    goals = await mem.get_goal_state(user_id)
    upcoming = await mem.query_upcoming(user_id, days=14)
    return {
        "preferences": prefs,
        "goals": goals,
        "upcoming_events": [{"event": e.event, "date": e.date} for e in upcoming],
    }


@traced_tool("write_entity_to_memory")
async def write_entity_to_memory(
    user_id: str,
    entity_name: str,
    entity_type: str,
    relation_type: str | None = None,
    since: str | None = None,
) -> dict:
    """Extract and persist an entity from user conversation into the Knowledge Graph."""
    from schemas import Entity, EntityType, Relation
    from datetime import datetime

    relations = []
    if relation_type:
        relations.append(Relation(type=relation_type, since=since))

    try:
        etype = EntityType(entity_type.lower())
    except ValueError:
        etype = EntityType.event

    entity = Entity(
        user_id=user_id,
        entity_name=entity_name,
        entity_type=etype,
        relations=relations,
    )
    await _memory().write_entity(entity)
    return {"status": "saved", "entity": entity_name}


@traced_tool("clear_pending_reschedule")
async def clear_pending_reschedule(user_id: str) -> dict:
    """Clear pending reschedule tasks after user confirms rescheduling is done."""
    await _memory().update_preference(user_id, "pending_reschedule", None)
    return {"status": "cleared"}


@traced_tool("store_conversation_memory")
async def store_conversation_memory(user_id: str, text: str, metadata: dict | None = None) -> dict:
    """Compress and store a conversation insight as a searchable memory embedding."""
    await _memory().store_memory(user_id, text, metadata)
    return {"status": "stored", "text": text[:80]}


@traced_tool("retrieve_relevant_memories")
async def retrieve_relevant_memories(user_id: str, query: str, k: int = 3) -> dict:
    """Retrieve the most relevant past memories for the current context."""
    results = await _memory().retrieve_similar(user_id, query, k)
    return {"memories": results, "count": len(results)}