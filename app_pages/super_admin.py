import streamlit as st
import pandas as pd
from utils.db import (
    get_teams, add_team, delete_team, update_team, get_all_users, add_team_member, 
    update_team_member, delete_team_member, DuplicateUserError, update_team_member_fields
)

st.title("Super admin console")

tabs = st.tabs(["Manage teams", "Manage users & admins", "JIRA Configuration"])

# Manage Teams tab
with tabs[0]:
    with st.form("create_team_form"):
        st.subheader("Create new team")
        t_name = st.text_input("Team name", placeholder="e.g. Platform Team")
        if st.form_submit_button("Create team", type="primary"):
            if t_name.strip():
                add_team(t_name.strip())
                st.success(f"Team '{t_name.strip()}' created successfully.")
                st.rerun()
            else:
                st.error("Please enter a valid team name.")

    st.divider()
    st.subheader("All teams")
    teams_df = get_teams()
    if teams_df.empty:
        st.info("No teams created yet.")
    else:
        teams_display = teams_df.set_index('id')
        edited_teams = st.data_editor(
            teams_display,
            column_config={
                "name": st.column_config.TextColumn("Team name")
            },
            key="teams_editor",
            hide_index=True,
        )
        
        col_btn1, col_btn2 = st.columns([2, 5])
        with col_btn1:
            if st.button("Save team changes", type="primary", key="save_teams_btn"):
                editor_state = st.session_state.get("teams_editor", {})
                edited_rows = editor_state.get("edited_rows", {})
                if edited_rows:
                    for idx, changes in edited_rows.items():
                        db_id = teams_display.index[int(idx)]
                        if "name" in changes:
                            update_team(db_id, changes["name"])
                    st.success("Team names updated successfully.")
                    st.rerun()
                else:
                    st.info("No changes to save.")
                
        st.divider()
        st.subheader("Delete team")
        del_team_name = st.selectbox(
            "Select team to delete",
            [""] + teams_df['name'].tolist(),
            key="delete_team_select"
        )
        if del_team_name and st.button("Delete team", type="primary", key="delete_team_btn"):
            team_row = teams_df[teams_df['name'] == del_team_name].iloc[0]
            delete_team(team_row['id'])
            st.success("Team deleted successfully.")
            st.rerun()

# Manage Users & Admins tab
with tabs[1]:
    teams_df = get_teams()
    # Teams may be empty when initializing, but we still want to add Super Admins who don't need a team!
    with st.form("create_user_form"):
        st.subheader("Add new user / admin")
        
        c1, c2 = st.columns(2)
        with c1:
            u_name = st.text_input("Full name", placeholder="e.g. Jane Doe")
            u_email = st.text_input("Email", placeholder="jane.doe@moglix.com")
        with c2:
            u_pass = st.text_input("Password", type="password", placeholder="Password")
            u_role = st.selectbox("User role", ["Team User", "Team Admin", "Super Admin"])

        c3, c4 = st.columns(2)
        with c3:
            team_options = teams_df['name'].tolist() if not teams_df.empty else []
            u_team = st.selectbox("Assign to team (ignored for Super Admin)", options=["N/A"] + team_options)
        with c4:
            d_role = st.selectbox("Developer role", ["Backend", "Frontend", "QA", "PM", "EM", "Super Admin"])

        if st.form_submit_button("Add user / admin", type="primary"):
            if u_name.strip() and u_email.strip() and u_pass.strip():
                if u_role == "Super Admin":
                    t_id = None
                    final_role = "Super Admin"
                else:
                    if u_team == "N/A" or not u_team:
                        st.error("Please assign a team for Team Users and Team Admins.")
                        st.stop()
                    t_id = teams_df[teams_df['name'] == u_team]['id'].values[0]
                    final_role = d_role
                try:
                    add_team_member(
                        name=u_name.strip(),
                        role=final_role,
                        email=u_email.strip(),
                        password=u_pass.strip(),
                        user_role=u_role,
                        team_id=t_id
                    )
                    st.success("User added successfully.")
                    st.rerun()
                except DuplicateUserError as e:
                    st.error(str(e))
            else:
                st.error("Please fill in all user details.")

    st.divider()
    st.subheader("All users & admins")

    # Team filter
    team_options = teams_df['name'].tolist() if not teams_df.empty else []
    selected_team_filter = st.selectbox("Filter by team", ["All Teams"] + team_options, key="team_filter")

    users_df = get_all_users()
    if users_df.empty:
        st.info("No users registered.")
    else:
        # Map team names
        team_map = dict(zip(teams_df['id'], teams_df['name'])) if not teams_df.empty else {}
        team_reverse_map = {v: k for k, v in team_map.items()}
        
        # Prepare dataframe for editing (exclude current active logged-in super admin to prevent lockouts)
        current_active_id = st.session_state.user['id']
        edit_users_df = users_df[users_df['id'] != current_active_id].copy()
        
        if edit_users_df.empty:
            st.info("No other users registered.")
        else:
            edit_users_df['team_name'] = edit_users_df['team_id'].map(team_map).fillna("N/A")

            # Filter by selected team
            if selected_team_filter != "All Teams":
                edit_users_df = edit_users_df[edit_users_df['team_name'] == selected_team_filter]

            if edit_users_df.empty:
                st.info(f"No users found for team '{selected_team_filter}'.")
            else:
                edit_users_display = edit_users_df.drop(columns=['password'], errors='ignore').set_index('id')
                
                # Render Data Editor
                edited_users = st.data_editor(
                    edit_users_display,
                    column_config={
                        "name": st.column_config.TextColumn("Full name"),
                        "email": st.column_config.TextColumn("Email"),
                        "user_role": st.column_config.SelectboxColumn("User role", options=["Super Admin", "Team Admin", "Team User"]),
                        "team_name": st.column_config.SelectboxColumn("Team", options=["N/A"] + list(team_map.values())),
                        "role": st.column_config.SelectboxColumn("Developer role", options=["Backend", "Frontend", "QA", "PM", "EM", "Super Admin"]),
                        "daily_sp": st.column_config.NumberColumn("Daily SP", min_value=0.0, step=0.5),
                        "bug_p": st.column_config.NumberColumn("Bug buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                        "adhoc_p": st.column_config.NumberColumn("Adhoc buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                        "ceremony_p": st.column_config.NumberColumn("Ceremony buffer (%)", min_value=0.0, max_value=100.0, step=1.0),
                    },
                    key="users_editor",
                    hide_index=True,
                )
                
                col_save_btn, _ = st.columns([2, 5])
                with col_save_btn:
                    if st.button("Save user changes", type="primary", key="save_users_btn"):
                        editor_state = st.session_state.get("users_editor", {})
                        edited_rows = editor_state.get("edited_rows", {})
                        if edited_rows:
                            for idx, changes in edited_rows.items():
                                db_id = edit_users_display.index[int(idx)]
                                
                                # Map team_name to team_id if modified
                                if "team_name" in changes:
                                    sel_team_name = changes.pop("team_name")
                                    if sel_team_name == "N/A" or not sel_team_name:
                                        changes["team_id"] = None
                                    else:
                                        sel_team_id = team_reverse_map.get(sel_team_name)
                                        changes["team_id"] = str(sel_team_id) if sel_team_id else None
                                    
                                update_team_member_fields(db_id, changes)
                            st.success("User information updated successfully.")
                            st.rerun()
                        else:
                            st.info("No changes to save.")
                        
                st.divider()
                st.subheader("Delete user")
                del_user_name = st.selectbox(
                    "Select user to delete",
                    [""] + edit_users_df['name'].tolist(),
                    key="delete_user_select"
                )
                if del_user_name and st.button("Delete user", type="primary", key="delete_user_btn"):
                    user_row = edit_users_df[edit_users_df['name'] == del_user_name].iloc[0]
                    delete_team_member(user_row['id'])
                    st.success("User deleted successfully.")
                    st.rerun()

# JIRA Configuration tab
with tabs[2]:
    st.subheader("JIRA Connection Settings")
    st.markdown("Configure JIRA credentials for sprint sync. Credentials are encrypted and stored securely.")

    from utils.db import get_jira_credentials, save_jira_credentials

    # Load existing config
    existing = get_jira_credentials()
    base_url_val = existing.get("base_url", "") if existing else ""
    email_val = existing.get("email", "") if existing else ""
    sp_field_val = existing.get("story_points_field", "customfield_10119") if existing else "customfield_10119"
    start_date_field = existing.get("start_date_field", "") if existing else ""
    end_date_field = existing.get("end_date_field", "") if existing else ""
    actual_sp_field = existing.get("actual_sp_field", "") if existing else ""

    with st.form("jira_config_form"):
        st.markdown("### Connection Details")
        c1, c2 = st.columns(2)
        with c1:
            jira_base_url = st.text_input(
                "JIRA Base URL",
                value=base_url_val,
                placeholder="https://yourcompany.atlassian.net",
                help="Your JIRA instance URL"
            )
            jira_email = st.text_input(
                "JIRA Email",
                value=email_val,
                placeholder="user@company.com",
                help="Email used for JIRA API authentication"
            )
        with c2:
            jira_token = st.text_input(
                "Access Token",
                value="",
                type="password",
                placeholder="Leave blank to keep existing token",
                help="API token for JIRA (create at https://id.atlassian.com/manage-profile/security/api-tokens)"
            )
            jira_sp_field = st.text_input(
                "Story Points Field ID",
                value=sp_field_val,
                placeholder="customfield_10119",
                help="Custom field ID for story points in JIRA"
            )

        st.markdown("### Custom Field Mappings (Optional)")
        c3, c4 = st.columns(2)
        with c3:
            jira_start_date_field = st.text_input(
                "Start Date Field ID",
                value=start_date_field,
                placeholder="e.g. customfield_10310",
                help="Optional: custom field ID for start date"
            )
            jira_actual_sp_field = st.text_input(
                "Actual SP Field ID",
                value=actual_sp_field,
                placeholder="e.g. customfield_10119",
                help="Optional: custom field ID for actual story points"
            )
        with c4:
            jira_end_date_field = st.text_input(
                "End Date Field ID",
                value=end_date_field,
                placeholder="e.g. customfield_10332",
                help="Optional: custom field ID for end date"
            )

        if st.form_submit_button("Save JIRA Configuration", type="primary"):
            if jira_base_url.strip() and jira_email.strip():
                token = jira_token.strip() if jira_token.strip() else (existing.get("token") if existing else "")
                if token:
                    save_jira_credentials(
                        token,
                        jira_email.strip(),
                        jira_base_url.strip(),
                        jira_sp_field.strip(),
                        start_date_field=jira_start_date_field.strip() if jira_start_date_field.strip() else None,
                        end_date_field=jira_end_date_field.strip() if jira_end_date_field.strip() else None,
                        actual_sp_field=jira_actual_sp_field.strip() if jira_actual_sp_field.strip() else None
                    )
                    st.success("JIRA credentials saved securely.")
                    st.rerun()
                else:
                    st.error("Access Token is required.")
            else:
                st.error("Base URL and Email are required.")

    # Show current status
    st.divider()
    if existing:
        masked_token = existing.get("token", "")
        if len(masked_token) > 10:
            masked_token = masked_token[:6] + "..." + masked_token[-4:]
        sp = existing.get('story_points_field', 'N/A')
        start = existing.get('start_date_field', 'N/A')
        end = existing.get('end_date_field', 'N/A')
        actual = existing.get('actual_sp_field', 'N/A')
        st.success(f"Credentials configured. Token: `{masked_token}` | URL: {existing.get('base_url', '')}")
        st.caption(f"Story Points: {sp} | Start Date: {start} | End Date: {end} | Actual SP: {actual}")
    else:
        st.info("No JIRA credentials configured. Enter your details above to enable JIRA sync.")
