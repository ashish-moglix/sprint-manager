import pandas as pd

def get_workdays(start, end):
    """Calculate the number of business/work days in a range (inclusive)."""
    try:
        return len(pd.bdate_range(start, end))
    except Exception:
        return 0
