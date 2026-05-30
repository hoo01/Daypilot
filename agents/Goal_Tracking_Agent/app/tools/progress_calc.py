from app.schemas.domain import SubTask


def compute_progress_percent(sub_tasks: list[SubTask]) -> float:
    """Calculate goal completion percentage based purely on sub-task completion.

    Formula: (completed_count / total_count) * 100
    Returns 0.0 for an empty list to avoid ZeroDivisionError.
    All sub-tasks are weighted equally (v1; weighted scoring deferred to v2).
    """
    if not sub_tasks:
        return 0.0
    completed = sum(1 for t in sub_tasks if t.is_completed)
    return round((completed / len(sub_tasks)) * 100, 2)
