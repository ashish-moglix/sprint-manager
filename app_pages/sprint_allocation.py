import streamlit as st
import pandas as pd
from datetime import date
from utils.db import (
    get_sprints, get_team, get_leaves, get_holidays, get_backlog,
    update_ticket, clear_db_caches,
)
from utils.helpers import get_workdays, get_dev_allocated_sp, compute_sp, compute_actual_sp

st.title("Sprint allocation board")

sprints_df = get_sprints()
team_df = get_team()

if sprints_df.empty or team_df.empty:
    st.info("Create a sprint and add team members first.", icon=":material/info:")
    st.stop()

user_role = st.session_state.user.get("user_role", "Team User")
is_admin = user_role in ("Team Admin", "Scrum Master")

# Restrict access to Team Admin and Scrum Master only
if not is_admin:
    st.warning("This page is only accessible to Team Admin and Scrum Master roles.", icon=":material/lock:")
    st.stop()

sprint_names = sprints_df["name"].tolist()
active_sprint = sprints_df[sprints_df["status"] == "Active"]
active_name = active_sprint.iloc[0]["name"] if not active_sprint.empty else None
default_idx = sprint_names.index(active_name) if active_name in sprint_names else 0

selected_sprint = st.selectbox(
    "Select sprint",
    sprint_names,
    index=default_idx,
    key="alloc_sprint",
)

# Clear editor state when sprint changes so data_editor doesn't show stale data
prev_sprint_key = "alloc_sprint_prev"
if st.session_state.get(prev_sprint_key) != selected_sprint:
    # Wipe any editor state from a previous sprint selection
    keys_to_clear = [k for k in st.session_state if k.startswith("dev_") or k in ("unassigned", "unassigned_view_df") or k.endswith("_view_df")]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state[prev_sprint_key] = selected_sprint
    st.rerun()

s_row = sprints_df[sprints_df["name"] == selected_sprint].iloc[0]
s_id = s_row["id"]
s_start = pd.to_datetime(s_row["start_date"], format="mixed").date()
s_end = pd.to_datetime(s_row["end_date"], format="mixed").date()

tasks = get_backlog(s_id)
leaves = get_leaves(s_id)
hols = get_holidays(s_id, s_start, s_end)
work_days = get_workdays(s_start, s_end)
holiday_count = len(hols)

def _dev_capacity(dev_row):
    dev_leaves = leaves[leaves["name"] == dev_row["name"]]
    leave_days = dev_leaves["total_days"].sum() if not dev_leaves.empty else 0
    eff = max(work_days - holiday_count - leave_days, 0)
    dev_role = dev_row.get("role", "")
    daily_sp = 0.0 if dev_role in ("PM", "EM") else dev_row["daily_sp"]
    total_sp = eff * daily_sp
    bug_buf = dev_row.get("bug_p", 0.0)
    adhoc_buf = dev_row.get("adhoc_p", 0.0)
    cere_buf = dev_row.get("ceremony_p", 0.0)
    buffers = bug_buf + adhoc_buf + cere_buf
    avail = total_sp - buffers
    alloc = get_dev_allocated_sp(dev_row["name"], tasks)
    remaining = avail - alloc
    return {
        "total_sp": round(total_sp, 1),
        "buffers": round(buffers, 1),
        "available": round(avail, 1),
        "allocated": round(alloc, 1),
        "remaining": round(remaining, 1),
    }

def _get_dev_tasks(dev_name):
    if tasks.empty:
        return pd.DataFrame()
    mask = (
        (tasks["assignee"] == dev_name) |
        (tasks["backend_assignee"] == dev_name) |
        (tasks["frontend_assignee"] == dev_name) |
        (tasks["qa_assignee"] == dev_name)
    )
    return tasks[mask].copy()

def _get_unassigned_tasks():
    if tasks.empty:
        return pd.DataFrame()
    empty = ("", "NA")
    mask = (
        (tasks["assignee"].isna() | tasks["assignee"].isin(empty)) &
        (tasks["backend_assignee"].isna() | tasks["backend_assignee"].isin(empty)) &
        (tasks["frontend_assignee"].isna() | tasks["frontend_assignee"].isin(empty)) &
        (tasks["qa_assignee"].isna() | tasks["qa_assignee"].isin(empty))
    )
    return tasks[mask].copy()

def _auto_save_changes(editor_key):
    """Auto-save changes from data editor"""
    edited_state = st.session_state.get(editor_key, {})
    edited_rows = edited_state.get("edited_rows", {})

    if not edited_rows:
        return

    # Get the view dataframe from session state
    view_df = st.session_state.get(f"{editor_key}_view_df")
    if view_df is None:
        return

    for row_idx, changes in edited_rows.items():
        # Get the task ID directly from the view dataframe
        actual_row = view_df.iloc[row_idx]
        mongo_id = actual_row["id"]

        # Find this task in the full tasks dataframe to get current values
        task_row = tasks[tasks["id"] == mongo_id].iloc[0]

        # Build update with original values + changes
        update_data = {
            "ticket_id": changes.get("ticket_id", task_row["ticket_id"]),
            "title": changes.get("title", task_row["title"]),
            "assignee": changes.get("assignee", task_row.get("assignee")),
            "category": changes.get("category", task_row.get("category", "New Work")),
            "sp": float(changes.get("sp", task_row.get("sp", 0.0))),
            "actual_sp": float(task_row.get("actual_sp", 0.0)),
            "status": changes.get("status", task_row.get("status", "Todo")),
            "start_date": str(changes.get("start_date", task_row.get("start_date"))) if changes.get("start_date") else None,
            "end_date": str(changes.get("end_date", task_row.get("end_date"))) if changes.get("end_date") else None,
            "backend_assignee": changes.get("backend_assignee", task_row.get("backend_assignee")),
            "frontend_assignee": changes.get("frontend_assignee", task_row.get("frontend_assignee")),
            "qa_assignee": changes.get("qa_assignee", task_row.get("qa_assignee")),
            "backend_sp": float(changes.get("backend_sp", task_row.get("backend_sp", 0.0))),
            "frontend_sp": float(changes.get("frontend_sp", task_row.get("frontend_sp", 0.0))),
            "qa_sp": float(changes.get("qa_sp", task_row.get("qa_sp", 0.0))),
            "backend_status": changes.get("backend_status", task_row.get("backend_status", "Todo")),
            "frontend_status": changes.get("frontend_status", task_row.get("frontend_status", "Todo")),
            "qa_status": changes.get("qa_status", task_row.get("qa_status", "Todo")),
            "backend_start_date": str(changes.get("backend_start_date", task_row.get("backend_start_date"))) if changes.get("backend_start_date") else None,
            "backend_end_date": str(changes.get("backend_end_date", task_row.get("backend_end_date"))) if changes.get("backend_end_date") else None,
            "frontend_start_date": str(changes.get("frontend_start_date", task_row.get("frontend_start_date"))) if changes.get("frontend_start_date") else None,
            "frontend_end_date": str(changes.get("frontend_end_date", task_row.get("frontend_end_date"))) if changes.get("frontend_end_date") else None,
            "qa_start_date": str(changes.get("qa_start_date", task_row.get("qa_start_date"))) if changes.get("qa_start_date") else None,
            "qa_end_date": str(changes.get("qa_end_date", task_row.get("qa_end_date"))) if changes.get("qa_end_date") else None,
        }

        update_ticket(mongo_id, **update_data)

    clear_db_caches()
    st.session_state[f"{editor_key}_saved"] = True

def _render_editable_task_table(df, dev_name=None, tab_key=""):
    """Render an editable task table for admin users"""
    if df.empty:
        st.info("No tasks found.", icon=":material/info:")
        return

    # Select columns to display (must include 'id' for mapping back to original task)
    cols = ["id", "ticket_id", "title", "category", "assignee", "backend_assignee", "frontend_assignee", "qa_assignee",
            "status", "backend_status", "frontend_status", "qa_status",
            "sp", "backend_sp", "frontend_sp", "qa_sp",
            "start_date", "end_date",
            "backend_start_date", "backend_end_date",
            "frontend_start_date", "frontend_end_date",
            "qa_start_date", "qa_end_date",
            "actual_sp"]

    available = [c for c in cols if c in df.columns]
    view_df = df[available].copy().reset_index(drop=True)

    # Convert date columns
    for col in available:
        if "date" in col:
            view_df[col] = pd.to_datetime(view_df[col], format="mixed", errors="coerce").dt.date

    # Compute SP and Actual SP
    view_df['sp'] = view_df.apply(compute_sp, axis=1)
    view_df['actual_sp'] = view_df.apply(compute_actual_sp, axis=1)

    # Configure columns
    team_names = team_df["name"].tolist()
    col_config = {
        "id": None,  # Hide the ID column
        "ticket_id": st.column_config.TextColumn("Ticket", width="small", disabled=True),
        "title": st.column_config.TextColumn("Title", width="medium", disabled=True),
        "category": st.column_config.SelectboxColumn("Category", options=["New Work", "Spillover", "Bug Fix", "Adhoc"], width="small"),
        "assignee": st.column_config.SelectboxColumn("Assignee", options=[""] + team_names, width="small"),
        "backend_assignee": st.column_config.SelectboxColumn("Backend", options=["NA"] + team_names, width="small"),
        "frontend_assignee": st.column_config.SelectboxColumn("Frontend", options=["NA"] + team_names, width="small"),
        "qa_assignee": st.column_config.SelectboxColumn("QA", options=["NA"] + team_names, width="small"),
        "status": st.column_config.SelectboxColumn("Status", options=["Todo", "In Progress", "Done"], width="small"),
        "backend_status": st.column_config.SelectboxColumn("BE Status", options=["NA", "Todo", "In Progress", "Done"], width="small"),
        "frontend_status": st.column_config.SelectboxColumn("FE Status", options=["NA", "Todo", "In Progress", "Done"], width="small"),
        "qa_status": st.column_config.SelectboxColumn("QA Status", options=["NA", "Todo", "In Progress", "Done"], width="small"),
        "sp": st.column_config.NumberColumn("SP", min_value=0.0, step=0.5, width="small", disabled=True),
        "backend_sp": st.column_config.NumberColumn("BE SP", min_value=0.0, step=0.5, width="small", disabled=True),
        "frontend_sp": st.column_config.NumberColumn("FE SP", min_value=0.0, step=0.5, width="small", disabled=True),
        "qa_sp": st.column_config.NumberColumn("QA SP", min_value=0.0, step=0.5, width="small", disabled=True),
        "start_date": st.column_config.DateColumn("Start", width="small"),
        "end_date": st.column_config.DateColumn("End", width="small"),
        "backend_start_date": st.column_config.DateColumn("BE Start", width="small"),
        "backend_end_date": st.column_config.DateColumn("BE End", width="small"),
        "frontend_start_date": st.column_config.DateColumn("FE Start", width="small"),
        "frontend_end_date": st.column_config.DateColumn("FE End", width="small"),
        "qa_start_date": st.column_config.DateColumn("QA Start", width="small"),
        "qa_end_date": st.column_config.DateColumn("QA End", width="small"),
        "actual_sp": st.column_config.NumberColumn("Actual SP", min_value=0.0, step=0.5, width="small", disabled=True),
    }

    # Store view_df mapping in session state for the auto-save callback
    st.session_state[f"{tab_key}_view_df"] = view_df

    st.data_editor(
        view_df,
        column_config=col_config,
        key=tab_key,
        hide_index=True,
        num_rows="fixed",
        use_container_width=True,
        on_change=lambda: _auto_save_changes(tab_key),
    )

# Build tab list: each developer + Unassigned
dev_names = team_df["name"].tolist()
tab_labels = []
dev_caps = {}

for _, dev in team_df.iterrows():
    cap = _dev_capacity(dev)
    dev_caps[dev["name"]] = cap
    dev_tasks = _get_dev_tasks(dev["name"])
    task_count = len(dev_tasks)
    tab_labels.append(f"{dev['name']}  ({cap['allocated']}/{cap['available']} SP) [{task_count}]")

unassigned = _get_unassigned_tasks()
tab_labels.append(f":material/help_outline: Unassigned [{len(unassigned)}]")

tabs = st.tabs(tab_labels)

# Developer tabs
for i, dev_name in enumerate(dev_names):
    with tabs[i]:
        cap = dev_caps[dev_name]

        # Metrics row
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Capacity", f"{cap['total_sp']}")
        m2.metric("Buffers", f"{cap['buffers']}")
        m3.metric("Available", f"{cap['available']}")
        m4.metric("Allocated", f"{cap['allocated']}")

        delta_color = "normal" if cap["remaining"] >= 0 else "inverse"
        m5.metric("Remaining", f"{cap['remaining']}", delta=f"{cap['remaining']:+.1f}", delta_color=delta_color)

        # Editable task table for this developer
        dev_tasks = _get_dev_tasks(dev_name)
        _render_editable_task_table(dev_tasks, dev_name=dev_name, tab_key=f"dev_{i}")

# Unassigned tab
with tabs[-1]:
    st.subheader(f"Unassigned tasks ({len(unassigned)})")
    _render_editable_task_table(unassigned, dev_name=None, tab_key="unassigned")

# If any editor auto-saved during this run, trigger a rerun OUTSIDE the callback so metrics refresh
saved_keys = [k for k in st.session_state if k.endswith("_saved")]
if saved_keys:
    for k in saved_keys:
        del st.session_state[k]
    st.rerun()
