import streamlit as st
import pandas as pd
from utils.db import get_sprints, get_team, get_backlog

st.set_page_config(page_title="Developer Performance", page_icon=":material/bar_chart:", layout="wide")

st.title("Developer Performance Dashboard")
st.caption("Analyze individual developer performance across the last 6 sprints (including active)")

# Fetch data
sprints_df = get_sprints()
team_df = get_team()

if sprints_df.empty or team_df.empty:
    st.warning("No sprints or team data available.")
    st.stop()

# Include active + archived sprints
# Include archived sprints plus the currently active one
active_sprints = sprints_df[sprints_df['status'] == 'Active']
archived_sprints = sprints_df[sprints_df['status'] == 'Archived'].copy()

# Combine active + archived, sort by end_date descending
last_sprints = pd.concat([active_sprints, archived_sprints], ignore_index=True)
if last_sprints.empty:
    st.info("No sprints found.")
    st.stop()

last_sprints['end_date_dt'] = pd.to_datetime(last_sprints['end_date'], errors='coerce')
last_sprints = last_sprints.sort_values('end_date_dt', ascending=False)

# Take last 6 sprints
last_sprints = last_sprints.head(6)
if len(last_sprints) < 6:
    st.info(f"Only {len(last_sprints)} sprint(s) available. Showing all available.")

sprint_names = last_sprints['name'].tolist()
sprint_ids = last_sprints['id'].tolist()

# Prepare data structures
dev_perf_rows = []  # for summary table
dev_sprint_tasks = {}  # (dev_name, sprint_id) -> list of task dicts for detail view

for sprint_id, sprint_name in zip(sprint_ids, sprint_names):
    backlog = get_backlog(sprint_id)
    if backlog.empty:
        # No tasks in this sprint
        for _, dev in team_df.iterrows():
            dev_name = dev['name']
            dev_perf_rows.append({
                'Sprint': sprint_name,
                'Developer': dev_name,
                'Role': dev.get('role', ''),
                'Estimated SP': 0,
                'Actual SP': 0,
                'Completed Tasks': 0,
                'Not Done Tasks': 0,
                'Missing Start Date': 0,
                'Missing End Date': 0,
                'Tasks': []
            })
            dev_sprint_tasks[(dev_name, sprint_id)] = []
        continue

    # Ensure needed columns exist
    for col in ['sp', 'actual_sp', 'status', 'start_date', 'end_date',
                'backend_sp', 'frontend_sp', 'qa_sp',
                'backend_status', 'frontend_status', 'qa_status',
                'assignee', 'backend_assignee', 'frontend_assignee', 'qa_assignee']:
        if col not in backlog.columns:
            backlog[col] = None

    # Fill NaN for SP columns
    backlog['sp'] = pd.to_numeric(backlog['sp'], errors='coerce').fillna(0)
    backlog['actual_sp'] = pd.to_numeric(backlog['actual_sp'], errors='coerce').fillna(0)
    for role_col in ['backend_sp', 'frontend_sp', 'qa_sp']:
        if role_col in backlog.columns:
            backlog[role_col] = pd.to_numeric(backlog[role_col], errors='coerce').fillna(0)

    # Determine task completion based on status (fallback to role statuses)
    def is_done(row):
        status = str(row.get('status', '')).lower()
        if status == 'done':
            return True
        # check role statuses
        for role_status_col in ['backend_status', 'frontend_status', 'qa_status']:
            rs = row.get(role_status_col)
            if pd.notna(rs) and str(rs).lower() == 'done':
                return True
        return False

    backlog['_done'] = backlog.apply(is_done, axis=1)
    # Missing dates
    backlog['_missing_start'] = backlog['start_date'].isna() | (backlog['start_date'] == '')
    backlog['_missing_end'] = backlog['end_date'].isna() | (backlog['end_date'] == '')

    # Iterate developers
    for _, dev in team_df.iterrows():
        dev_name = dev['name']
        role = dev.get('role', '')
        # Tasks assigned to this developer (any assignee field)
        mask = (
            (backlog['assignee'] == dev_name) |
            (backlog['backend_assignee'] == dev_name) |
            (backlog['frontend_assignee'] == dev_name) |
            (backlog['qa_assignee'] == dev_name)
        )
        dev_tasks = backlog[mask].copy()
        dev_sprint_tasks[(dev_name, sprint_id)] = dev_tasks.to_dict('records')

        # Compute metrics
        estimated_sp = dev_tasks['sp'].sum()
        actual_sp = dev_tasks['actual_sp'].sum()
        completed_tasks = dev_tasks['_done'].sum()
        not_done_tasks = (~dev_tasks['_done']).sum()
        missing_start = dev_tasks['_missing_start'].sum()
        missing_end = dev_tasks['_missing_end'].sum()

        dev_perf_rows.append({
            'Sprint': sprint_name,
            'Developer': dev_name,
            'Role': role,
            'Estimated SP': round(estimated_sp, 1),
            'Actual SP': round(actual_sp, 1),
            'Completed Tasks': int(completed_tasks),
            'Not Done Tasks': int(not_done_tasks),
            'Missing Start Date': int(missing_start),
            'Missing End Date': int(missing_end),
            'Tasks': len(dev_tasks)
        })

# Convert to DataFrame for display and charts
perf_df = pd.DataFrame(dev_perf_rows)
if perf_df.empty:
    st.info("No performance data to display.")
    st.stop()

# --- Summary Charts ---
st.subheader("Performance Trends (Last 6 Sprints)")

# Developer selector for charts
dev_options = ['All'] + sorted(perf_df['Developer'].unique().tolist())
selected_dev = st.selectbox("Select Developer", dev_options, index=0)

chart_df = perf_df.copy()
if selected_dev != 'All':
    chart_df = chart_df[chart_df['Developer'] == selected_dev]

# Ensure sprint order is correct (as per last_sprints order)
chart_df['Sprint'] = pd.Categorical(chart_df['Sprint'], categories=sprint_names, ordered=True)
chart_df = chart_df.sort_values('Sprint')

# SP chart: show Estimated SP and Actual SP as separate simple series
sp_est = chart_df.pivot_table(index='Sprint', values='Estimated SP', aggfunc='sum', fill_value=0)
sp_act = chart_df.pivot_table(index='Sprint', values='Actual SP', aggfunc='sum', fill_value=0)
sp_combined = pd.DataFrame({'Estimated SP': sp_est['Estimated SP'], 'Actual SP': sp_act['Actual SP']}).reindex(index=sprint_names).fillna(0)
st.line_chart(sp_combined)

# Task chart: show Completed and Not Done as separate series
task_done = chart_df.pivot_table(index='Sprint', values='Completed Tasks', aggfunc='sum', fill_value=0)
task_not = chart_df.pivot_table(index='Sprint', values='Not Done Tasks', aggfunc='sum', fill_value=0)
task_combined = pd.DataFrame({'Completed': task_done['Completed Tasks'], 'Not Done': task_not['Not Done Tasks']}).reindex(index=sprint_names).fillna(0)
st.bar_chart(task_combined)

# --- Detailed Tables ---
st.subheader("Detailed Performance Table")
# Show summary table with formatting
display_cols = ['Sprint', 'Developer', 'Role', 'Estimated SP', 'Actual SP',
                'Completed Tasks', 'Not Done Tasks', 'Missing Start Date', 'Missing End Date', 'Tasks']
st.dataframe(
    perf_df[display_cols],
    use_container_width=True,
    hide_index=True,
    column_config={
        "Sprint": st.column_config.TextColumn("Sprint"),
        "Developer": st.column_config.TextColumn("Developer"),
        "Role": st.column_config.TextColumn("Role"),
        "Estimated SP": st.column_config.NumberColumn("Est. SP", format="%.1f"),
        "Actual SP": st.column_config.NumberColumn("Act. SP", format="%.1f"),
        "Completed Tasks": st.column_config.NumberColumn("Done"),
        "Not Done Tasks": st.column_config.NumberColumn("Not Done"),
        "Missing Start Date": st.column_config.NumberColumn("No Start"),
        "Missing End Date": st.column_config.NumberColumn("No End"),
        "Tasks": st.column_config.NumberColumn("Total Tasks"),
    }
)

# Drill-down: select developer and sprint to see task list
st.subheader("Task Details")
col1, col2 = st.columns(2)
with col1:
    drill_dev = st.selectbox("Developer", options=sorted(perf_df['Developer'].unique().tolist()), key="drill_dev")
with col2:
    drill_sprint = st.selectbox("Sprint", options=sprint_names, key="drill_sprint")

# Find sprint_id for selected sprint name
sprint_id_map = dict(zip(last_sprints['name'], last_sprints['id']))
selected_sprint_id = sprint_id_map.get(drill_sprint)

if selected_sprint_id is not None:
    tasks_list = dev_sprint_tasks.get((drill_dev, selected_sprint_id), [])
    if tasks_list:
        tasks_df = pd.DataFrame(tasks_list)
        # Select relevant columns for display
        show_cols = ['ticket_id', 'title', 'status', 'sp', 'actual_sp',
                     'start_date', 'end_date',
                     'backend_status', 'frontend_status', 'qa_status',
                     'assignee', 'backend_assignee', 'frontend_assignee', 'qa_assignee']
        show_cols = [c for c in show_cols if c in tasks_df.columns]
        if not tasks_df.empty:
            tasks_df['start_date'] = pd.to_datetime(tasks_df['start_date'], errors='coerce').dt.date
            tasks_df['end_date'] = pd.to_datetime(tasks_df['end_date'], errors='coerce').dt.date
            st.dataframe(
                tasks_df[show_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ticket_id": st.column_config.TextColumn("Ticket ID"),
                    "title": st.column_config.TextColumn("Title"),
                    "status": st.column_config.TextColumn("Status"),
                    "sp": st.column_config.NumberColumn("Est. SP", format="%.1f"),
                    "actual_sp": st.column_config.NumberColumn("Act. SP", format="%.1f"),
                    "start_date": st.column_config.DateColumn("Start"),
                    "end_date": st.column_config.DateColumn("End"),
                    "assignee": st.column_config.TextColumn("Assignee"),
                    "backend_assignee": st.column_config.TextColumn("BE"),
                    "frontend_assignee": st.column_config.TextColumn("FE"),
                    "qa_assignee": st.column_config.TextColumn("QA"),
                    "backend_status": st.column_config.TextColumn("BE Status"),
                    "frontend_status": st.column_config.TextColumn("FE Status"),
                    "qa_status": st.column_config.TextColumn("QA Status"),
                }
            )
        else:
            st.info("No tasks found for this developer in the selected sprint.")
    else:
        st.info("No tasks found for this developer in the selected sprint.")
else:
    st.info("Select a sprint to view task details.")

st.caption("Note: Estimated SP is from planning; Actual SP is computed from workdays × 2 (or from role-specific SPs). Missing dates indicate tasks without start or end dates.")