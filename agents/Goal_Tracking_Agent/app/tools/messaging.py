from datetime import date


def format_behind_schedule_reminder(
    goal_title: str,
    completed_count: int,
    total_count: int,
    deadline: date,
) -> str:
    remaining = total_count - completed_count
    deadline_str = deadline.strftime("%B %-d")
    return (
        f"You're behind on your goal '{goal_title}' — {remaining} of {total_count} "
        f"sub-tasks remain and your deadline is {deadline_str}. "
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
    orig_dl = original_deadline.strftime("%B %-d")
    ext_dl = extended_deadline.strftime("%B %-d")
    return (
        f"Your goal: \"{goal_title}\"\n"
        f"Based on your history, similar goals typically take ~{overrun_pct}% longer than planned.\n"
        f"Estimated effort with adjustment: {adjusted_effort_minutes} min "
        f"(original: {original_effort_minutes} min).\n\n"
        f"Suggested adjustments:\n"
        f"  A. Extend deadline to {ext_dl} (originally {orig_dl})\n"
        f"  B. Reduce target to {reduced_scope}\n"
        f"  C. Keep original goal — I will send daily reminders to help you stay on track\n\n"
        f"How would you like to proceed?"
    )
