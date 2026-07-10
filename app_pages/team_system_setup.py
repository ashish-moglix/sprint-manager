import streamlit as st
import pandas as pd
from utils.db import (
    get_sprints, get_team, add_team_member, update_team_member, delete_team_member,
    launch_sprint, update_sprint, delete_sprint
)

# Title
st.title("Roster & lifecycle")

t_abs = st.tabs(["Manage team", "Manage sprints"])

# Manage team tab
with t_abs[0]:
    with st.form("add_tm"):
        st.subheader("Add new team member")
        nm = st.text_input("Full name", key="member_name_input")
        rl = st.selectbox("Role", ["Backend", "Frontend", "QA"], key="member_role_select")
        
        # Buffer input sliders
        b_p = st.slider("Prod bug buffer (%)", 0, 30, 15, key="member_bug_slider")
        a_p = st.slider("Adhoc buffer (%)", 0, 20, 10, key="member_adhoc_slider")
        c_p = st.slider("Ceremonies buffer (%)", 0, 25, 10, key="member_cere_slider")
        
        if st.form_submit_button("Add member", type="primary"):
            if nm.strip():
                add_team_member(nm.strip(), rl, b_p, a_p, c_p)
                st.rerun()
            else:
                st.error("Please enter a valid name.", icon=":material/error:")

    st.divider()
    st.subheader("Current roster")
    team_df = get_team()
    
    if team_df.empty:
        st.info("No team members found. Add some above.", icon=":material/info:")
    else:
        team_display = team_df.set_index('id')
        edited_t = st.data_editor(
            team_display,
            column_config={
                "name": st.column_config.TextColumn("Full name"),
                "role": st.column_config.SelectboxColumn("Role", options=["Backend", "Frontend", "QA"]),
                "daily_sp": st.column_config.NumberColumn("Daily SP", min_value=0.0, step=0.5),
                "bug_p": st.column_config.NumberColumn("Bug buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                "adhoc_p": st.column_config.NumberColumn("Adhoc buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                "ceremony_p": st.column_config.NumberColumn("Ceremony buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
            },
            key="team_editor",
        )

        col_save_t, _ = st.columns([2, 4])
        if col_save_t.button("Save roster changes", type="primary", key="save_roster_btn"):
            for idx, row in edited_t.iterrows():
                update_team_member(idx, row['name'], row['role'], row['daily_sp'], row['bug_p'], row['adhoc_p'], row['ceremony_p'])
            st.rerun()

        st.subheader("Delete team member")
        del_mem = st.selectbox(
            "Select member to delete",
            [""] + team_df['name'].tolist(),
            key="delete_member_select"
        )
        if del_mem and st.button("Delete member", type="primary", key="delete_member_btn"):
            mem_row = team_df[team_df['name'] == del_mem].iloc[0]
            delete_team_member(mem_row['id'])
            st.rerun()

# Manage sprints tab
with t_abs[1]:
    with st.form("sp_launch"):
        st.subheader("Launch new sprint")
        s_n = st.text_input("Sprint name", key="sprint_name_input")
        s_r = st.date_input("Range", value=[], key="sprint_range_picker")
        
        if st.form_submit_button("Launch sprint", type="primary"):
            if s_n.strip() and len(s_r) == 2:
                launch_sprint(s_n.strip(), s_r[0], s_r[1])
                st.rerun()
            else:
                st.error("Please provide both a sprint name and a complete date range.", icon=":material/error:")

    st.divider()
    st.subheader("All sprints")
    sprints_df = get_sprints()
    
    if not sprints_df.empty:
        sprints_display = sprints_df.copy()
        sprints_display['start_date'] = pd.to_datetime(sprints_display['start_date']).dt.date
        sprints_display['end_date'] = pd.to_datetime(sprints_display['end_date']).dt.date
        sprints_display = sprints_display.set_index('id')

        edited_s = st.data_editor(
            sprints_display,
            column_config={
                "name": "Sprint name",
                "start_date": st.column_config.DateColumn("Start date"),
                "end_date": st.column_config.DateColumn("End date"),
                "status": st.column_config.SelectboxColumn("Status", options=["Active", "Archived"]),
            },
            key="sprints_editor",
        )

        if st.button("Save sprint changes", type="primary", key="save_sprints_btn"):
            for idx, row in edited_s.iterrows():
                update_sprint(idx, row['name'], row['start_date'], row['end_date'], row['status'])
            st.rerun()

        st.subheader("Delete sprint")
        del_sprint = st.selectbox(
            "Select sprint to delete (cascades to all backlog, leaves, holidays)",
            [""] + sprints_df['name'].tolist(),
            key="delete_sprint_select"
        )
        if del_sprint and st.button("Delete sprint & all related data", type="primary", key="delete_sprint_btn"):
            delete_sprint(del_sprint)
            st.rerun()
    else:
        st.info("No sprints configured.", icon=":material/info:")
