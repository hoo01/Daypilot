from schemas.goal_domain import SubTask


def compute_progress_percent(sub_tasks: list[SubTask]) -> float:
    """Equal-weight completion: completed / total * 100. Returns 0.0 if no sub-tasks."""
    if not sub_tasks:
        return 0.0
    completed = sum(1 for t in sub_tasks if t.is_completed)
    return round(completed / len(sub_tasks) * 100, 2)
