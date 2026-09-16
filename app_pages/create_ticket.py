import streamlit as st
import pandas as pd
from datetime import date
from utils.db import get_sprints, get_team, add_ticket, get_backlog, get_leaves, get_holidays, get_current_team_id
from utils.helpers import get_dev_allocated_sp, get_workdays

st.set_page_config(page_title="Create Ticket", page_icon=":material/add_circle:", layout="wide")

if not st.session_state.get("user"):
    st.warning("Please log in to access this page.")
    st.stop()

user = st.session_state.user
is_team_user = (user.get("user_role") == "Team User")

if is_team_user:
    st.info("Ticket creation is restricted to Admin/Scrum Master/PM roles.")
    st.stop()

sprints_df = get_sprints()
if sprints_df.empty:
    st.warning("No sprints found. Create a sprint in Team & System Setup first.")
    st.stop()

active_sprint = sprints_df[sprints_df["status"] == "Active"].iloc[0] if not sprints_df[sprints_df["status"] == "Active"].empty else None

st.title("Create New Ticket")
st.caption("Add a new ticket with full details including role-specific assignments and estimates")

sprint_names = sprints_df["name"].tolist()
default_index = sprint_names.index(active_sprint["name"]) if active_sprint is not None else 0
selected_sprint_name = st.selectbox("Select Sprint", sprint_names, index=default_index)
selected_s_row = sprints_df[sprints_df["name"] == selected_sprint_name].iloc[0]
selected_s_id = selected_s_row["id"]
s_start = pd.to_datetime(selected_s_row["start_date"], format="mixed")
s_end = pd.to_datetime(selected_s_row["end_date"], format="mixed")

team_df = get_team()
if team_df.empty:
    st.warning("No team members found. Add team members in Team & System Setup first.")
    st.stop()

team_names = team_df["name"].tolist()

st.markdown("---")

with st.container(border=True):
    st.subheader("Basic Information")

    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        ticket_id = st.text_input("Ticket ID", placeholder="e.g. PROJ-123")
    with c2:
        title = st.text_input("Title", placeholder="Short task description")
    with c3:
        total_sp = st.number_input("Total Est. SP", min_value=0.0, value=2.0, step=0.5)

    description = st.text_area("Description", placeholder="Detailed description of the ticket...", height=120)

    c4, c5 = st.columns(2)
    with c4:
        primary_assignee = st.selectbox("Primary Assignee", team_names)
    with c5:
        category = st.selectbox("Category", ["New Work", "Spillover", "Bug Fix", "Adhoc"])

st.markdown("---")

role_configs = [
    ("Backend", "backend", ":material/code:"),
    ("Frontend", "frontend", ":material/web:"),
    ("QA", "qa", ":material/bug_report:"),
]

role_data = {}

for role_label, role_key, role_icon in role_configs:
    with st.container(border=True):
        st.subheader(f"{role_icon} {role_label}")

        c1, c2 = st.columns(2)
        with c1:
            assignee = st.selectbox(
                f"{role_label} Assignee",
                ["NA"] + team_names,
                key=f"{role_key}_assignee",
            )
        with c2:
            sp = st.number_input(
                f"{role_label} SP",
                min_value=0.0,
                value=0.0,
                step=0.5,
                key=f"{role_key}_sp",
            )

        c3, c4 = st.columns(2)
        with c3:
            start_date = st.date_input(
                f"{role_label} Start Date",
                value=s_start.date(),
                key=f"{role_key}_start",
            )
        with c4:
            end_date = st.date_input(
                f"{role_label} End Date",
                value=s_end.date(),
                key=f"{role_key}_end",
            )

        role_data[role_key] = {
            "assignee": assignee,
            "sp": sp,
            "start_date": start_date,
            "end_date": end_date,
        }

st.markdown("---")

with st.container(border=True):
    st.subheader(f":material/insights: Capacity Metrics - {primary_assignee}")

    dev_row = team_df[team_df["name"] == primary_assignee].iloc[0]
    wk_days = get_workdays(s_start.date(), s_end.date())
    hols_in_sprint = len(get_holidays(selected_s_id, s_start.date(), s_end.date()))
    leaves_df = get_leaves(selected_s_id)
    dev_leaves_sum = leaves_df[
        (leaves_df["name"] == primary_assignee) & (leaves_df["sprint_id"] == selected_s_id)
    ]["total_days"].sum()

    eff_days = max(wk_days - hols_in_sprint - dev_leaves_sum, 0)
    dev_role = dev_row.get("role", "")
    daily_sp = 0.0 if dev_role in ["PM", "EM"] else dev_row["daily_sp"]
    total_dev_sp = eff_days * daily_sp

    dev_bug_p = dev_row.get("bug_p", 15.0)
    dev_adhoc_p = dev_row.get("adhoc_p", 10.0)
    dev_cere_p = dev_row.get("ceremony_p", 10.0)

    dev_buffers = total_dev_sp * (dev_bug_p + dev_adhoc_p + dev_cere_p) / 100
    dev_avail = total_dev_sp - dev_buffers

    backlog_df = get_backlog(selected_s_id)
    dev_alloced = get_dev_allocated_sp(primary_assignee, backlog_df)
    dev_remaining = dev_avail - dev_alloced

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Gross Capacity", f"{total_dev_sp:.1f}")
    m2.metric("Buffers", f"{dev_buffers:.1f}")
    m3.metric("Available", f"{dev_avail:.1f}")
    m4.metric("Allocated", f"{dev_alloced:.1f}")
    m5.metric("Remaining", f"{dev_remaining:.1f}", delta=f"{dev_remaining:+.1f}")

st.markdown("---")

if st.button("Create Ticket", type="primary", use_container_width=True):
    if not ticket_id.strip():
        st.error("Ticket ID is required.")
    elif not title.strip():
        st.error("Title is required.")
    else:
        be = role_data["backend"]
        fe = role_data["frontend"]
        qa = role_data["qa"]

        add_ticket(
            sprint_id=selected_s_id,
            ticket_id=ticket_id.strip(),
            title=title.strip(),
            assignee=primary_assignee,
            role=dev_role,
            category=category,
            sp=total_sp,
            backend_assignee=be["assignee"] if be["assignee"] != "NA" else None,
            frontend_assignee=fe["assignee"] if fe["assignee"] != "NA" else None,
            qa_assignee=qa["assignee"] if qa["assignee"] != "NA" else None,
            backend_sp=be["sp"] if be["sp"] > 0 else None,
            frontend_sp=fe["sp"] if fe["sp"] > 0 else None,
            qa_sp=qa["sp"] if qa["sp"] > 0 else None,
            backend_start_date=str(be["start_date"]) if be["assignee"] != "NA" else None,
            backend_end_date=str(be["end_date"]) if be["assignee"] != "NA" else None,
            frontend_start_date=str(fe["start_date"]) if fe["assignee"] != "NA" else None,
            frontend_end_date=str(fe["end_date"]) if fe["assignee"] != "NA" else None,
            qa_start_date=str(qa["start_date"]) if qa["assignee"] != "NA" else None,
            qa_end_date=str(qa["end_date"]) if qa["assignee"] != "NA" else None,
        )
        st.success(f"Ticket **{ticket_id.strip()}** created successfully in sprint **{selected_sprint_name}**!")
        st.balloons()
