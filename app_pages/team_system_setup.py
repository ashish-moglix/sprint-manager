import streamlit as st
import pandas as pd
from utils.db import (
    get_sprints, get_team, add_team_member, update_team_member, delete_team_member,
    create_sprint, start_sprint, stop_sprint, update_sprint, delete_sprint, DuplicateUserError, update_team_member_fields, get_mongo_db
)
from bson import ObjectId
from utils.hash import hash_password

# Title
st.title("Roster & lifecycle")

user_role = st.session_state.user.get('user_role', 'Team User')
t_abs = st.tabs(["Manage team", "Manage sprints"])

# Manage team tab
with t_abs[0]:
    if user_role == 'Team Admin':
        with st.form("add_tm"):
            st.subheader("Add new team member")
            
            c1, c2 = st.columns(2)
            with c1:
                nm = st.text_input("Full name", key="member_name_input")
                email_input = st.text_input("Email (optional, defaults to name@moglix.com)", key="member_email_input")
            with c2:
                rl = st.selectbox("Role", ["Backend", "Frontend", "QA", "PM", "EM"], key="member_role_select")
                pass_input = st.text_input("Password (optional, defaults to Welcome@123)", type="password", key="member_password_input")
            
            # Buffer input sliders
            b_p = st.slider("Prod bug buffer (%)", 0, 30, 15, key="member_bug_slider")
            a_p = st.slider("Adhoc buffer (%)", 0, 20, 10, key="member_adhoc_slider")
            c_p = st.slider("Ceremonies buffer (%)", 0, 25, 10, key="member_cere_slider")
            
            if st.form_submit_button("Add member", type="primary"):
                if nm.strip():
                    try:
                        add_team_member(
                            name=nm.strip(), 
                            role=rl, 
                            bug_p=b_p, 
                            adhoc_p=a_p, 
                            ceremony_p=c_p,
                            email=email_input.strip() if email_input.strip() else None,
                            password=pass_input.strip() if pass_input.strip() else None,
                            user_role="Team User"
                        )
                        st.success(f"Member '{nm.strip()}' added successfully.")
                        st.rerun()
                    except DuplicateUserError as e:
                        st.error(str(e))
                else:
                    st.error("Please enter a valid name.", icon=":material/error:")
    else:
        st.info("Only team admins can add team members.", icon=":material/info:")

    st.divider()
    st.subheader("Current roster")
    team_df = get_team()
    
    if team_df.empty:
        st.info("No team members found.", icon=":material/info:")
    else:
        team_display = team_df.set_index('id')
        
        # Display editable roster only for Admin
        if user_role == 'Team Admin':
            edited_t = st.data_editor(
                team_display,
                column_config={
                    "name": st.column_config.TextColumn("Full name"),
                    "email": st.column_config.TextColumn("Email"),
                    "password": st.column_config.TextColumn("Password"),
                    "user_role": st.column_config.SelectboxColumn("User role", options=["Team Admin", "Team User"]),
                    "role": st.column_config.SelectboxColumn("Developer role", options=["Backend", "Frontend", "QA", "PM", "EM"]),
                    "daily_sp": st.column_config.NumberColumn("Daily SP", min_value=0.0, step=0.5),
                    "bug_p": st.column_config.NumberColumn("Bug buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                    "adhoc_p": st.column_config.NumberColumn("Adhoc buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                    "ceremony_p": st.column_config.NumberColumn("Ceremony buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                },
                key="team_editor",
            )

            col_save_t, _ = st.columns([2, 4])
            if col_save_t.button("Save roster changes", type="primary", key="save_roster_btn"):
                editor_state = st.session_state.get("team_editor", {})
                edited_rows = editor_state.get("edited_rows", {})
                if edited_rows:
                    for idx, changes in edited_rows.items():
                        db_id = team_display.index[int(idx)]
                        # Hash password if modified
                        if "password" in changes and changes["password"]:
                            changes["password"] = hash_password(changes["password"])
                        
                        update_team_member_fields(db_id, changes)
                    st.success("Roster changes saved.")
                    st.rerun()
                else:
                    st.info("No changes to save.")

            st.subheader("Delete team member")
            del_mem = st.selectbox(
                "Select member to delete",
                [""] + team_df['name'].tolist(),
                key="delete_member_select"
            )
            if del_mem and st.button("Delete member", type="primary", key="delete_member_btn"):
                mem_row = team_df[team_df['name'] == del_mem].iloc[0]
                delete_team_member(mem_row['id'])
                st.success("Member deleted.")
                st.rerun()
        else:
            # For Team Users, show as a read-only dataframe, omitting passwords
            read_only_df = team_df.drop(columns=['password'], errors='ignore')
            st.dataframe(read_only_df.set_index('name')[['email', 'role', 'daily_sp', 'bug_p', 'adhoc_p', 'ceremony_p']])

# Manage sprints tab
with t_abs[1]:
    sprints_df = get_sprints()
    
    if user_role == 'Team Admin':
        st.subheader("Manage Sprint Lifecycle")
        
        # 1. Create a Draft Sprint
        with st.form("sp_create_draft"):
            st.markdown("### 1. Create Draft Sprint")
            s_n = st.text_input("Sprint Name", key="sprint_name_input", placeholder="e.g. Sprint 2")
            s_r = st.date_input("Planned Date Range", value=[], key="sprint_range_picker")
            
            if st.form_submit_button("Create Sprint Draft", type="primary"):
                if s_n.strip() and len(s_r) == 2:
                    create_sprint(s_n.strip(), s_r[0], s_r[1])
                    st.success(f"Sprint '{s_n.strip()}' created as Draft.")
                    st.rerun()
                else:
                    st.error("Please provide both a sprint name and a complete planned date range.", icon=":material/error:")

        # 2. Start a Draft Sprint (only if no other active sprint exists)
        drafts_df = sprints_df[sprints_df['status'] == 'Draft'] if not sprints_df.empty else pd.DataFrame()
        active_sprint = sprints_df[sprints_df['status'] == 'Active'].iloc[0] if not sprints_df.empty and not sprints_df[sprints_df['status'] == 'Active'].empty else None
        
        c_start, c_stop = st.columns(2)
        
        with c_start:
            st.markdown("### 2. Start Sprint")
            if drafts_df.empty:
                st.info("No draft sprints available to start. Create one above.")
            elif active_sprint is not None:
                st.warning(f"Sprint '{active_sprint['name']}' is currently active. Stop it first to start a new one.")
            else:
                with st.form("sp_start"):
                    sel_draft = st.selectbox("Select Draft Sprint", drafts_df['name'].tolist())
                    act_start_date = st.date_input("Actual Start Date", value=pd.to_datetime(drafts_df[drafts_df['name'] == sel_draft].iloc[0]['start_date']).date())
                    
                    if st.form_submit_button("Start Sprint", type="primary"):
                        draft_id = drafts_df[drafts_df['name'] == sel_draft].iloc[0]['id']
                        try:
                            start_sprint(draft_id, act_start_date)
                            st.success(f"Sprint '{sel_draft}' is now Active.")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                            
        with c_stop:
            st.markdown("### 3. Stop Sprint")
            if active_sprint is None:
                st.info("No sprint is currently active.")
            else:
                with st.form("sp_stop"):
                    st.write(f"Active Sprint: **{active_sprint['name']}**")
                    act_end_date = st.date_input("Actual End Date", value=pd.to_datetime(active_sprint['end_date']).date())
                    
                    if st.form_submit_button("Stop Sprint", type="primary"):
                        stop_sprint(active_sprint['id'], act_end_date)
                        with st.spinner("Compiling and archiving sprint performance report..."):
                            from utils.reports_generator import compile_and_save_report
                            try:
                                compile_and_save_report(active_sprint['id'])
                                st.success(f"Sprint '{active_sprint['name']}' has been stopped and archived. Performance report successfully generated.")
                            except Exception as e:
                                st.error(f"Sprint stopped, but report generation failed: {str(e)}")
                        st.rerun()

    st.divider()
    st.subheader("All Sprints & Lag Statistics")
    sprints_df = get_sprints()
    
    if not sprints_df.empty:
        sprints_display = sprints_df.copy()
        
        # Calculate lag stats
        lag_stats_list = []
        for _, row in sprints_display.iterrows():
            stats = []
            p_start = pd.to_datetime(row['start_date'])
            p_end = pd.to_datetime(row['end_date'])
            
            a_start_val = row.get('actual_start_date')
            a_start = pd.to_datetime(a_start_val) if pd.notna(a_start_val) and a_start_val else None
            
            a_end_val = row.get('actual_end_date')
            a_end = pd.to_datetime(a_end_val) if pd.notna(a_end_val) and a_end_val else None
            
            if a_start:
                start_diff = (a_start - p_start).days
                if start_diff > 0:
                    stats.append(f"Late start: +{start_diff}d")
                elif start_diff < 0:
                    stats.append(f"Early start: {start_diff}d")
                else:
                    stats.append("Start: On time")
            else:
                stats.append("Start: N/A")
                
            if a_end:
                end_diff = (a_end - p_end).days
                if end_diff > 0:
                    stats.append(f"Late end: +{end_diff}d")
                elif end_diff < 0:
                    stats.append(f"Early end: {end_diff}d")
                else:
                    stats.append("End: On time")
            else:
                stats.append("End: N/A")
                
            lag_stats_list.append(", ".join(stats))
            
        sprints_display['Lag Stats'] = lag_stats_list
        sprints_display['start_date'] = pd.to_datetime(sprints_display['start_date']).dt.date
        sprints_display['end_date'] = pd.to_datetime(sprints_display['end_date']).dt.date
        sprints_display['actual_start_date'] = pd.to_datetime(sprints_display['actual_start_date']).dt.date
        sprints_display['actual_end_date'] = pd.to_datetime(sprints_display['actual_end_date']).dt.date
        
        sprints_display = sprints_display.set_index('id')

        # Drop internal fields
        cols_to_show = ['name', 'start_date', 'end_date', 'actual_start_date', 'actual_end_date', 'status', 'Lag Stats']
        existing_cols = [c for c in cols_to_show if c in sprints_display.columns]
        
        if user_role == 'Team Admin':
            # Let admins edit planned dates and names only
            edited_s = st.data_editor(
                sprints_display[existing_cols],
                column_config={
                    "name": "Sprint name",
                    "start_date": st.column_config.DateColumn("Planned Start"),
                    "end_date": st.column_config.DateColumn("Planned End"),
                    "actual_start_date": st.column_config.DateColumn("Actual Start", disabled=True),
                    "actual_end_date": st.column_config.DateColumn("Actual End", disabled=True),
                    "status": st.column_config.TextColumn("Status", disabled=True),
                    "Lag Stats": st.column_config.TextColumn("Lag Stats", disabled=True),
                },
                key="sprints_editor",
            )

            if st.button("Save sprint changes", type="primary", key="save_sprints_btn"):
                editor_state = st.session_state.get("sprints_editor", {})
                edited_rows = editor_state.get("edited_rows", {})
                if edited_rows:
                    db = get_mongo_db()
                    for idx, changes in edited_rows.items():
                        db_id = sprints_display.index[int(idx)]
                        if "start_date" in changes:
                            changes["start_date"] = str(changes["start_date"])
                        if "end_date" in changes:
                            changes["end_date"] = str(changes["end_date"])
                        db['sprints'].update_one(
                            {"_id": ObjectId(db_id)},
                            {"$set": changes}
                        )
                    from utils.db import clear_db_caches
                    clear_db_caches()
                    st.success("Sprint changes saved.")
                    st.rerun()
                else:
                    st.info("No changes to save.")

            st.subheader("Delete sprint")
            del_sprint = st.selectbox(
                "Select sprint to delete (cascades to all backlog, leaves, holidays)",
                [""] + sprints_df['name'].tolist(),
                key="delete_sprint_select"
            )
            if del_sprint and st.button("Delete sprint & all related data", type="primary", key="delete_sprint_btn"):
                delete_sprint(del_sprint)
                st.success("Sprint deleted.")
                st.rerun()
        else:
            st.dataframe(sprints_display[existing_cols])
    else:
        st.info("No sprints configured.", icon=":material/info:")
