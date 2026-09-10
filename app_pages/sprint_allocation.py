import streamlit as st
import pandas as pd
from datetime import date
from utils.db import (
    get_sprints, get_team, get_leaves, get_holidays, get_backlog,
    update_ticket, clear_db_caches, add_ticket_comment, get_ticket_comments,
)
from utils.helpers import get_workdays, get_dev_allocated_sp, compute_sp, compute_actual_sp

@st.dialog("Add comment", width="large")
def _comment_dialog(sprint_id, ticket_id, ticket_title, mention_options, user_name, user_email):
    """Popup dialog for adding a comment."""
    st.markdown(f"**{ticket_id} — {ticket_title}**")
    input_key = f"dialog_comment_input"
    mention_key = f"dialog_mention"

    selectable = [n for n in mention_options.keys() if n != user_name]
    selected_mentions = []
    if selectable:
        selected_mentions = st.multiselect(
            "Tag team members",
            options=selectable,
            key=mention_key,
            placeholder="Select to @mention",
        )

    if selected_mentions:
        tag_chips = " ".join([f"`@{m}`" for m in selected_mentions])
        st.markdown(f"**Tagging:** {tag_chips}", help="These @mentions will be appended to your comment")

    new_comment = st.text_area(
        "Add comment",
        key=input_key,
        placeholder="What happened on this ticket? (dev/QA update)",
        height=120,
    )

    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("Submit", key="dialog_submit", type="primary", use_container_width=True):
            body = new_comment.strip()
            if selected_mentions:
                mention_str = " ".join([f"@{m}" for m in selected_mentions])
                body = f"{body} {mention_str}".strip() if body else mention_str
            if body:
                add_ticket_comment(sprint_id, ticket_id, user_name, user_email, body, mention_options=mention_options)
                st.rerun()
            else:
                st.warning("Comment cannot be empty.")
    with b2:
        if st.button("Cancel", key="dialog_cancel", use_container_width=True):
            st.rerun()

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

def _get_completion_indicators(row):
    """Return completion status indicators for visual display."""
    # Helper to check if status is done
    def is_done(val):
        return str(val).lower() == 'done' if pd.notna(val) else False

    status_done = is_done(row.get('status'))
    be_done = is_done(row.get('backend_status'))
    fe_done = is_done(row.get('frontend_status'))
    qa_done = is_done(row.get('qa_status'))

    # Build indicator string
    indicators = []

    if status_done and be_done and fe_done and qa_done:
        indicators.append("🟢 Live")  # All done + status done
    elif status_done:
        indicators.append("🟢 Done")  # Just status done
    else:
        # Show individual role completion
        if be_done:
            indicators.append("🔵 BE")
        if fe_done:
            indicators.append("🟡 FE")
        if qa_done:
            indicators.append("🟠 QA")

    return " ".join(indicators) if indicators else "⚪ Todo"


def _render_editable_task_table(df, dev_name=None, tab_key=""):
    """Render an editable task table for admin users"""
    if df.empty:
        st.info("No tasks found.", icon=":material/info:")
        return

    # Detect JIRA column
    has_jira_col = "jira_url" in df.columns and df["jira_url"].notna().any()

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

    # Add JIRA link column if present
    if has_jira_col:
        view_df['jira_url'] = df['jira_url'].values

    # Add completion indicators column
    view_df['completion'] = view_df.apply(_get_completion_indicators, axis=1)

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
        "completion": st.column_config.TextColumn("Progress", width="small", disabled=True),
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

    if has_jira_col:
        col_config["jira_url"] = st.column_config.LinkColumn("JIRA", width="small", display_text="Open")

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

def _render_ticket_comments(sprint_id, ticket_id, ticket_title, tab_idx, safe_id,
                            be_assignee=None, fe_assignee=None, qa_assignee=None,
                            jira_url=None, completion=None):
    """Render comment thread: expander for history + add-comment button beside it."""
    comments = get_ticket_comments(sprint_id, ticket_id)

    parts = []
    if be_assignee and be_assignee not in ("", "NA", None):
        parts.append(f"🔵 BE: {be_assignee}")
    if fe_assignee and fe_assignee not in ("", "NA", None):
        parts.append(f"🟡 FE: {fe_assignee}")
    if qa_assignee and qa_assignee not in ("", "NA", None):
        parts.append(f"🟠 QA: {qa_assignee}")
    assignee_tag = "  |  ".join(parts)

    header = f"{ticket_id} — {ticket_title}"
    if completion and completion != "⚪ Todo":
        header = f"{header}  {completion}"
    if assignee_tag:
        header = f"{header}  |  {assignee_tag}"

    expander_label = f"{header}  |  💬 {len(comments)}"
    if jira_url:
        expander_label = f"{expander_label}  |  [JIRA ↗]({jira_url})"

    mention_options = {}
    for _, member in team_df.iterrows():
        m_name = member.get("name", "")
        m_jira_id = member.get("jira_account_id")
        if m_name:
            mention_options[m_name] = m_jira_id

    col_expand, col_add = st.columns([10, 1])
    with col_expand:
        with st.expander(expander_label, expanded=False):
            if comments:
                for c in reversed(comments):
                    author = c.get("author", "Unknown")
                    created = c.get("created", "")
                    date_str = created[:10] if created else ""
                    if c.get("source") == "jira":
                        source_tag = " · JIRA"
                    elif c.get("synced"):
                        source_tag = " · synced"
                    else:
                        source_tag = " · local"
                    body = c.get("body", "")
                    st.markdown(f"**{author}** · {date_str}{source_tag}")
                    st.caption(body)
                    st.divider()
            else:
                st.caption("No comments yet.")
    with col_add:
        if st.button("💬", key=f"add_{tab_idx}_{safe_id}", help="Add comment", use_container_width=True):
            _comment_dialog(sprint_id, ticket_id, ticket_title, mention_options,
                           st.session_state.user.get("name", ""), st.session_state.user.get("email", ""))

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
        dev_role = team_df[team_df["name"] == dev_name]["role"].values[0] if dev_name in team_df["name"].values else None

        # Metrics row
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Capacity", f"{cap['total_sp']}")
        m2.metric("Buffers", f"{cap['buffers']}")
        m3.metric("Available", f"{cap['available']}")
        m4.metric("Allocated", f"{cap['allocated']}")

        delta_color = "normal" if cap["remaining"] >= 0 else "inverse"
        m5.metric("Remaining", f"{cap['remaining']}", delta=f"{cap['remaining']:+.1f}", delta_color=delta_color)

        # Get dev tasks for this developer
        dev_tasks = _get_dev_tasks(dev_name)

        # --- Filters ---
        # Map dev role to default role filter selection
        role_filter_options = ["All", "Assignee", "BE", "FE", "QA"]
        role_to_filter = {
            "Backend": "BE",
            "Frontend": "FE",
            "QA": "QA",
            "Fullstack": "All",
        }
        default_role_filter = role_to_filter.get(dev_role, "All")

        f1, f2 = st.columns(2)
        with f1:
            role_filter = st.selectbox(
                "Filter by role",
                role_filter_options,
                index=role_filter_options.index(default_role_filter),
                key=f"role_filter_{i}",
            )
        with f2:
            status_filter = st.multiselect(
                "Filter by status",
                ["Todo", "In Progress", "Done"],
                default=["Todo", "In Progress"],
                key=f"status_filter_{i}",
            )

        # Apply role filter
        if role_filter == "Assignee":
            dev_tasks = dev_tasks[dev_tasks["assignee"] == dev_name]
        elif role_filter == "BE":
            dev_tasks = dev_tasks[dev_tasks["backend_assignee"] == dev_name]
        elif role_filter == "FE":
            dev_tasks = dev_tasks[dev_tasks["frontend_assignee"] == dev_name]
        elif role_filter == "QA":
            dev_tasks = dev_tasks[dev_tasks["qa_assignee"] == dev_name]
        # "All" shows all tasks for this dev (already filtered by _get_dev_tasks)

        # Apply status filter
        if status_filter:
            # Combine all role statuses for filtering
            def _row_status_in_filter(row):
                statuses = []
                if pd.notna(row.get('status')):
                    statuses.append(str(row['status']))
                if pd.notna(row.get('backend_status')) and row.get('backend_status') != 'NA':
                    statuses.append(str(row['backend_status']))
                if pd.notna(row.get('frontend_status')) and row.get('frontend_status') != 'NA':
                    statuses.append(str(row['frontend_status']))
                if pd.notna(row.get('qa_status')) and row.get('qa_status') != 'NA':
                    statuses.append(str(row['qa_status']))
                # If any of the statuses match the filter, show the row
                return any(s in status_filter for s in statuses)

            status_mask = dev_tasks.apply(_row_status_in_filter, axis=1)
            dev_tasks = dev_tasks[status_mask]

        # Editable task table for this developer
        _render_editable_task_table(dev_tasks, dev_name=dev_name, tab_key=f"dev_{i}")

        # Per-ticket comment threads for this developer
        if not dev_tasks.empty:
            st.markdown("**Ticket activity**")
            st.caption("Local comments auto-push to JIRA for synced tickets. Sync from JIRA to pull remote comments. Latest first.")
            for tidx, (_, trow) in enumerate(dev_tasks.iterrows()):
                tid = trow.get("ticket_id", f"row-{tidx}")
                ttitle = trow.get("title", "")
                # Sanitize ticket ID for use in Streamlit widget keys (hyphens invalid)
                safe_tid = str(tid).replace("-", "_")
                _render_ticket_comments(
                    s_id, tid, ttitle, tab_idx=f"{i}_{tidx}", safe_id=safe_tid,
                    be_assignee=trow.get("backend_assignee"),
                    fe_assignee=trow.get("frontend_assignee"),
                    qa_assignee=trow.get("qa_assignee"),
                    jira_url=trow.get("jira_url"),
                    completion=_get_completion_indicators(trow),
                )

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
