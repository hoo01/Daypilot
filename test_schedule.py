import asyncio
from agents.schedule import ScheduleAgent
from schemas import ScheduleInput, ScheduleTask
from schemas.health import HealthOutput
from schemas.goals import GoalsOutput
from schemas.schedule import UserPreferences

locked_blocks = [
    ScheduleTask(
        task_id="locked-1",
        title="Morning Routine",
        start_time="2026-05-25T07:00:00",
        end_time="2026-05-25T08:00:00",
        type="routine",
    ),
    ScheduleTask(
        task_id="locked-2",
        title="Urgent Client Call",
        start_time="2026-05-25T19:40:00",
        end_time="2026-05-25T20:30:00",
        type="calendar_event",
    ),
    ScheduleTask(
        task_id="locked-3",
        title="Group Project Meeting",
        start_time="2026-05-25T21:30:00",
        end_time="2026-05-25T23:00:00",
        type="calendar_event",
    ),
]

input_data = ScheduleInput(
    user_id="test_user",
    date="2026-05-25",
    replan_from_time="2026-05-25T19:30:00",
    locked_blocks=locked_blocks,
    health=HealthOutput(
        energy_level="medium",
        focus_window="9PM-1AM",
        cognitive_load_score=0.72,
        avoid_tasks=["back-to-back deep work"],
    ),
    goals=GoalsOutput(
        goal_status="behind_schedule",
        progress_percent=60.0,
        urgency="high",
        suggested_blocks=["Finish remaining 1h of linear algebra homework"],
    ),
    user_preferences=UserPreferences(
        preferred_work_hours="late_night",
        commute_minutes=30,
        break_frequency=90,
    ),
)


async def main():
    agent = ScheduleAgent()
    result = await agent.run(input_data)
    print(result.model_dump_json(indent=2))


asyncio.run(main())
