from functools import lru_cache
from db import get_db
from agents import (
    MemoryAgent, HealthAgent, GoalsAgent, RelationshipAgent,
    ScheduleAgent, GeoAgent, RealtimeAgent, CoordinatorAgent, IngestionAgent,
)


def get_memory() -> MemoryAgent:
    return MemoryAgent(get_db())


def get_coordinator() -> CoordinatorAgent:
    memory = get_memory()
    return CoordinatorAgent(
        memory=memory,
        health=HealthAgent(),
        goals=GoalsAgent(memory),
        relationship=RelationshipAgent(memory),
        schedule=ScheduleAgent(),
        geo=GeoAgent(),
        realtime=RealtimeAgent(),
    )


def get_realtime() -> RealtimeAgent:
    return RealtimeAgent()
