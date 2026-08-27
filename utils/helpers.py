import pandas as pd

def get_workdays(start, end):
    """Calculate the number of business/work days in a range (inclusive)."""
    try:
        return len(pd.bdate_range(start, end))
    except Exception:
        return 0


def get_dev_allocated_sp(dev_name: str, tasks_df: pd.DataFrame) -> float:
    """Sum role-specific story points for a developer across backend/frontend/qa."""
    if tasks_df is None or tasks_df.empty:
        return 0.0
    backend = tasks_df[tasks_df['backend_assignee'] == dev_name]['backend_sp'].sum()
    frontend = tasks_df[tasks_df['frontend_assignee'] == dev_name]['frontend_sp'].sum()
    qa = tasks_df[tasks_df['qa_assignee'] == dev_name]['qa_sp'].sum()
    return round(backend + frontend + qa, 2)
