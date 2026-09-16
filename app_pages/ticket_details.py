import streamlit as st
import pandas as pd
from utils.db import get_sprints, get_backlog, get_ticket_comments, get_current_team_id

st.set_page_config(page_title="Ticket Details", page_icon=":material/description:", layout="wide")

if not st.session_state.get("user"):
    st.warning("Please log in to access this page.")
    st.stop()

sprints_df = get_sprints()
if sprints_df.empty:
    st.warning("No sprints found.")
    st.stop()

st.title("Ticket Details")
st.caption("View complete information for any ticket")

query_params = st.query_params
url_ticket = query_params.get("ticket", "")
url_sprint = query_params.get("sprint", "")

sprint_names = sprints_df["name"].tolist()
active_sprint = sprints_df[sprints_df["status"] == "Active"]
default_sprint_idx = sprint_names.index(active_sprint.iloc[0]["name"]) if not active_sprint.empty else 0
if url_sprint:
    match = sprints_df[sprints_df["id"] == url_sprint]
    if not match.empty:
        default_sprint_idx = sprint_names.index(match.iloc[0]["name"])
selected_sprint_name = st.selectbox("Select Sprint", sprint_names, index=default_sprint_idx, key="td_sprint_select")
selected_s_row = sprints_df[sprints_df["name"] == selected_sprint_name].iloc[0]
selected_s_id = selected_s_row["id"]

backlog_df = get_backlog(selected_s_id)
if backlog_df.empty:
    st.info(f"No tickets found in sprint '{selected_sprint_name}'.")
    st.stop()

ticket_labels = backlog_df.apply(lambda r: f"{r['ticket_id']} - {r['title']}", axis=1).tolist()
ticket_ids = backlog_df["ticket_id"].tolist()

search_text = st.text_input("Search ticket by ID or title", placeholder="Type to filter...", key="td_search")
if search_text.strip():
    search_lower = search_text.strip().lower()
    filtered = [(label, tid) for label, tid in zip(ticket_labels, ticket_ids)
               if search_lower in label.lower()]
    if not filtered:
        st.info("No tickets match your search.")
        st.stop()
    display_labels = [f[0] for f in filtered]
else:
    filtered = list(zip(ticket_labels, ticket_ids))
    display_labels = ticket_labels

default_ticket_idx = 0
if url_ticket:
    for i, (label, tid) in enumerate(filtered):
        if tid == url_ticket:
            default_ticket_idx = i
            break
selected_label = st.selectbox("Select Ticket", display_labels, index=default_ticket_idx, key="td_ticket_select")

selected_idx = next(i for i, (label, tid) in enumerate(filtered) if label == selected_label)
ticket = backlog_df[backlog_df["ticket_id"] == filtered[selected_idx][1]].iloc[0]

selected_idx = ticket_labels.index(selected_label)
ticket = backlog_df.iloc[selected_idx]

st.markdown("---")

with st.container(border=True):
    st.subheader(":material/info: Basic Information")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Ticket ID:** {ticket.get('ticket_id', '')}")
        st.markdown(f"**Title:** {ticket.get('title', '')}")
        st.markdown(f"**Category:** {ticket.get('category', '')}")
        st.markdown(f"**Issue Type:** {ticket.get('issue_type', '') or 'N/A'}")
    with c2:
        st.markdown(f"**Status:** {ticket.get('status', '')}")
        st.markdown(f"**Assignee:** {ticket.get('assignee', '')}")
        st.markdown(f"**Role:** {ticket.get('role', '') or 'N/A'}")
        st.markdown(f"**Total SP:** {ticket.get('sp', 0)}")

    description = ticket.get("description", "") or ""
    st.text_area("Description", value=description, height=150, disabled=True, key="td_description")

st.markdown("---")

with st.container(border=True):
    st.subheader(":material/link: External Links")

    c1, c2 = st.columns(2)
    with c1:
        jira_url = ticket.get("jira_url", "")
        jira_key = ticket.get("jira_key", "")
        if jira_url:
            st.markdown(f"**JIRA:** [{jira_key or 'View in JIRA'}]({jira_url})")
            st.markdown(f"**JIRA Status:** {ticket.get('jira_status', '') or 'N/A'}")
        else:
            st.caption("Not linked to JIRA")

    with c2:
        parent_key = ticket.get("jira_parent_key", "")
        if parent_key:
            st.markdown(f"**Parent Ticket:** {parent_key}")
        else:
            st.caption("No parent (top-level ticket)")

        synced = ticket.get("synced_from_jira", False)
        st.markdown(f"**Synced from JIRA:** {'Yes' if synced else 'No'}")

st.markdown("---")

role_configs = [
    ("Backend", "backend", ":material/code:"),
    ("Frontend", "frontend", ":material/web:"),
    ("QA", "qa", ":material/bug_report:"),
]

for role_label, role_key, role_icon in role_configs:
    with st.container(border=True):
        st.subheader(f"{role_icon} {role_label}")

        assignee = ticket.get(f"{role_key}_assignee", "") or "NA"
        sp = ticket.get(f"{role_key}_sp", 0) or 0
        start = ticket.get(f"{role_key}_start_date", "")
        end = ticket.get(f"{role_key}_end_date", "")
        status = ticket.get(f"{role_key}_status", "") or "NA"

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"**Assignee:** {assignee}")
        with c2:
            st.markdown(f"**SP:** {sp}")
        with c3:
            st.markdown(f"**Dates:** {start or 'N/A'} → {end or 'N/A'}")
        with c4:
            st.markdown(f"**Status:** {status}")

st.markdown("---")

with st.container(border=True):
    st.subheader(":material/comment: Comments")

    comments = get_ticket_comments(str(selected_s_id), ticket.get("ticket_id", ""))

    if not comments:
        st.caption("No comments yet.")
    else:
        jira_comments = [c for c in comments if c.get("source") == "jira"]
        local_comments = [c for c in comments if c.get("source") != "jira"]

        if jira_comments:
            with st.expander(f":material/cloud: JIRA Comments ({len(jira_comments)})", expanded=True):
                for c in reversed(jira_comments):
                    author = c.get("author", "Unknown")
                    created = c.get("created", "")
                    date_str = created[:10] if created else ""
                    body = c.get("body", "")
                    st.markdown(f"**{author}** · {date_str} · :material/cloud: JIRA")
                    st.caption(body)
                    st.divider()

        if local_comments:
            with st.expander(f":material/chat: Local Comments ({len(local_comments)})", expanded=True):
                for c in reversed(local_comments):
                    author = c.get("author", "Unknown")
                    created = c.get("created", "")
                    date_str = created[:10] if created else ""
                    body = c.get("body", "")
                    synced_tag = " · synced" if c.get("synced") else ""
                    st.markdown(f"**{author}** · {date_str}{synced_tag}")
                    st.caption(body)
                    st.divider()
