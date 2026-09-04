import pandas as pd
from datetime import date

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
    backend = tasks_df[tasks_df['backend_assignee'] == dev_name]['backend_sp'].fillna(0).sum()
    frontend = tasks_df[tasks_df['frontend_assignee'] == dev_name]['frontend_sp'].fillna(0).sum()
    qa = tasks_df[tasks_df['qa_assignee'] == dev_name]['qa_sp'].fillna(0).sum()
    return round(backend + frontend + qa, 2)


def compute_sp(row) -> float:
    """Return estimated SP = backend_sp + frontend_sp + qa_sp."""
    return round(
        float(row.get('backend_sp') or 0.0) +
        float(row.get('frontend_sp') or 0.0) +
        float(row.get('qa_sp') or 0.0),
        2
    )


def compute_actual_sp(row) -> float:
    """Return actual SP from the most specific date range available.

    Priority: backend dates > frontend dates > qa dates > main dates.
    Falls back to existing actual_sp if no usable dates.
    """
    for prefix in ('backend', 'frontend', 'qa', ''):
        start_key = f'{prefix}_start_date' if prefix else 'start_date'
        end_key = f'{prefix}_end_date' if prefix else 'end_date'
        start_val = row.get(start_key)
        end_val = row.get(end_key)
        if start_val and end_val:
            try:
                start = pd.to_datetime(start_val).date() if not isinstance(start_val, date) else start_val
                end = pd.to_datetime(end_val).date() if not isinstance(end_val, date) else end_val
                if pd.isna(start) or pd.isna(end):
                    continue
                wd = get_workdays(start, end)
                return round(wd * 2, 2)
            except Exception:
                continue
    existing = row.get('actual_sp')
    return round(float(existing), 2) if existing is not None and not (isinstance(existing, float) and pd.isna(existing)) else 0.0
