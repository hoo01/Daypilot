from datetime import date


def format_behind_schedule_reminder(
    goal_title: str,
    completed_count: int,
    total_count: int,
    deadline: date,
) -> str:
    remaining = total_count - completed_count
    return (
        f"reminder: You're behind on your goal '{goal_title}' — "
        f"{remaining} of {total_count} sub-tasks remain "
        f"and your deadline is {deadline.isoformat()}. "
        f"Would you like to replan or adjust the goal?"
    )


def format_overdue_prompt(goal_title: str) -> str:
    return (
        f"Your goal '{goal_title}' has passed its deadline. "
        f"Would you like to replan it, or mark it as abandoned?"
    )


def format_feasibility_proposal(
    goal_title: str,
    original_effort_minutes: int,
    adjusted_effort_minutes: int,
    overrun_ratio: float,
    original_deadline: date,
    extended_deadline: date,
    reduced_scope: str,
) -> str:
    overrun_pct = int(overrun_ratio * 100)
    return (
        f"Based on your history, similar goals typically take ~{overrun_pct}% longer than planned "
        f"(original: {original_effort_minutes} min, adjusted: {adjusted_effort_minutes} min). "
        f"Suggested adjustments:\n"
        f"A. Extend deadline to {extended_deadline.isoformat()}\n"
        f"B. {reduced_scope}\n"
        f"C. Keep original goal '{goal_title}' — I will send daily reminders to help you stay on track."
    )
