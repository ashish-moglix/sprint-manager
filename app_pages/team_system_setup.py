import streamlit as st
import pandas as pd
from utils.db import (
    get_sprints, get_team, add_team_member, delete_team_member,
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
        
        if st.form_submit_button("Add member", type="primary"):
            if nm.strip():
                add_team_member(nm.strip(), rl)
                st.rerun()
            else:
                st.error("Please enter a valid name.", icon=":material/error:")

    st.divider()
    st.subheader("Current roster")
    team_df = get_team()
    
    if team_df.empty:
        st.info("No team members found. Add some above.", icon=":material/info:")
    else:
        for _, row in team_df.iterrows():
            ta, tb, tc = st.columns([3, 2, 1])
            with ta:
                st.markdown(f"**{row['name']}**")
            with tb:
                st.write(row['role'])
            with tc:
                if st.button("Delete", key=f"tm_del_{row['id']}", type="secondary"):
                    delete_team_member(row['id'])
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
