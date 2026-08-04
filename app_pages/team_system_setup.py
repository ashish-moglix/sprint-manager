import streamlit as st
import pandas as pd
from utils.db import (
    get_sprints, get_team, add_team_member, update_team_member, delete_team_member,
    create_sprint, start_sprint, stop_sprint, update_sprint, delete_sprint, DuplicateUserError,
    update_team_member_fields, get_mongo_db, clear_db_caches
)
from bson import ObjectId
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
        roster_cols = ['name', 'email', 'user_role', 'role', 'daily_sp', 'bug_p', 'adhoc_p', 'ceremony_p']
        team_display = team_df.drop(columns=['password', 'team_id'], errors='ignore').set_index('id')
        
        # Display editable roster only for Admin
        if user_role == 'Team Admin':
            f1, f2 = st.columns([2, 3])
            with f1:
                role_filter = st.selectbox(
                    "Filter by role",
                    ["All", "Backend", "Frontend", "QA", "PM", "EM"],
                    key="roster_role_filter",
                )
            with f2:
                roster_search = st.text_input("Search by name or email", placeholder="Type to filter...", key="roster_search")

            filtered_roster = team_display
            if role_filter != "All":
                filtered_roster = filtered_roster[filtered_roster['role'] == role_filter]
            if roster_search.strip():
                mask = filtered_roster['name'].str.contains(roster_search.strip(), case=False, na=False) | \
                       filtered_roster['email'].str.contains(roster_search.strip(), case=False, na=False)
                filtered_roster = filtered_roster[mask]

            roster_edit = filtered_roster[roster_cols].copy()
            roster_id_map = filtered_roster.index.values.tolist()
            roster_edit['Delete'] = False

            def _auto_save_roster():
                edited = st.session_state.get("team_editor", {}).get("edited_rows", {})
                if not edited:
                    return
                for row_idx, changes in edited.items():
                    if "Delete" in changes:
                        continue
                    if row_idx >= len(roster_id_map):
                        continue
                    mongo_id = roster_id_map[row_idx]
                    update_team_member_fields(mongo_id, changes)
                clear_db_caches()

            st.data_editor(
                roster_edit[roster_cols + ['Delete']],
                column_config={
                    "name": st.column_config.TextColumn("Full name"),
                    "email": st.column_config.TextColumn("Email"),
                    "user_role": st.column_config.SelectboxColumn("User role", options=["Team Admin", "Team User"]),
                    "role": st.column_config.SelectboxColumn("Developer role", options=["Backend", "Frontend", "QA", "PM", "EM"]),
                    "daily_sp": st.column_config.NumberColumn("Daily SP", min_value=0.0, step=0.5),
                    "bug_p": st.column_config.NumberColumn("Bug buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                    "adhoc_p": st.column_config.NumberColumn("Adhoc buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                    "ceremony_p": st.column_config.NumberColumn("Ceremony buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                    "Delete": st.column_config.CheckboxColumn("Delete", default=False),
                },
                key="team_editor",
                hide_index=True,
                num_rows="dynamic",
                on_change=_auto_save_roster,
            )

            edited_state = st.session_state.get("team_editor", {})
            edited_rows = edited_state.get("edited_rows", {})
            delete_marked = [
                (i, roster_id_map[i])
                for i, c in edited_rows.items()
                if c.get("Delete") and i < len(roster_id_map)
            ]
            if delete_marked:
                names_list = ", ".join(roster_edit.iloc[i]['name'] for i, _ in delete_marked)
                st.warning(f"Marked for deletion: **{names_list}**", icon=":material/warning:")
                if st.button("Confirm delete", type="primary", key="confirm_del_roster"):
                    deleted = 0
                    for _, mongo_id in delete_marked:
                        delete_team_member(mongo_id)
                        deleted += 1
                    if "team_editor" in st.session_state:
                        del st.session_state["team_editor"]
                    clear_db_caches()
                    st.success(f"Deleted {deleted} member(s).")
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
            status_filter = st.selectbox(
                "Filter by status",
                ["All", "Draft", "Active", "Archived"],
                key="sprint_status_filter",
            )
            filtered_sprints = sprints_display if status_filter == "All" else sprints_display[sprints_display['status'] == status_filter]

            sprints_edit = filtered_sprints[existing_cols].copy()
            sprint_id_map = filtered_sprints.index.values.tolist()
            sprints_edit['Delete'] = False

            def _auto_save_sprints():
                edited = st.session_state.get("sprints_editor", {}).get("edited_rows", {})
                if not edited:
                    return
                db = get_mongo_db()
                for row_idx, changes in edited.items():
                    if "Delete" in changes:
                        continue
                    if row_idx >= len(sprint_id_map):
                        continue
                    mongo_id = sprint_id_map[row_idx]
                    if "start_date" in changes:
                        changes["start_date"] = str(changes["start_date"])
                    if "end_date" in changes:
                        changes["end_date"] = str(changes["end_date"])
                    db['sprints'].update_one(
                        {"_id": ObjectId(mongo_id)},
                        {"$set": changes}
                    )
                clear_db_caches()

            st.data_editor(
                sprints_edit[existing_cols + ['Delete']],
                column_config={
                    "name": "Sprint name",
                    "start_date": st.column_config.DateColumn("Planned Start"),
                    "end_date": st.column_config.DateColumn("Planned End"),
                    "actual_start_date": st.column_config.DateColumn("Actual Start", disabled=True),
                    "actual_end_date": st.column_config.DateColumn("Actual End", disabled=True),
                    "status": st.column_config.TextColumn("Status", disabled=True),
                    "Lag Stats": st.column_config.TextColumn("Lag Stats", disabled=True),
                    "Delete": st.column_config.CheckboxColumn("Delete", default=False),
                },
                key="sprints_editor",
                hide_index=True,
                num_rows="dynamic",
                on_change=_auto_save_sprints,
            )

            edited_state = st.session_state.get("sprints_editor", {})
            edited_rows = edited_state.get("edited_rows", {})
            delete_marked = [
                (i, sprint_id_map[i])
                for i, c in edited_rows.items()
                if c.get("Delete") and i < len(sprint_id_map)
            ]
            if delete_marked:
                names_list = ", ".join(sprints_edit.iloc[i]['name'] for i, _ in delete_marked)
                st.warning(f"Marked for deletion: **{names_list}**", icon=":material/warning:")
                if st.button("Confirm delete", type="primary", key="confirm_del_sprints"):
                    deleted = 0
                    for _, row_name in delete_marked:
                        delete_sprint(sprints_edit.iloc[_]['name'])
                        deleted += 1
                    if "sprints_editor" in st.session_state:
                        del st.session_state["sprints_editor"]
                    clear_db_caches()
                    st.success(f"Deleted {deleted} sprint(s).")
                    st.rerun()
        else:
            st.dataframe(sprints_display[existing_cols], hide_index=True)
    else:
        st.info("No sprints configured.", icon=":material/info:")
