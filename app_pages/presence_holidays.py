import streamlit as st
import pandas as pd
from utils.db import (
    get_sprints, get_team, get_leaves_with_sprints, get_all_holidays,
    add_leave, update_leave, delete_leave, add_holiday, update_holiday, delete_holiday,
    clear_db_caches
)
from utils.helpers import get_workdays

# Title
st.title("Sprint presence setup")

sprints_df = get_sprints()
team_df = get_team()

if sprints_df.empty or team_df.empty:
    st.info("Create a sprint and add team members first.", icon=":material/info:")
else:
    team_names = team_df['name'].tolist()
    
    # Active sprint details for validation
    active = sprints_df[sprints_df['status'] == 'Active']
    active_sprint_name = active.iloc[0]['name'] if not active.empty else None
    
    # Sprint Selector at the top
    sprint_names = sprints_df['name'].tolist()
    default_index = sprint_names.index(active_sprint_name) if active_sprint_name in sprint_names else 0
    selected_sprint_name = st.selectbox("Select Sprint to View Presence & Holidays", sprint_names, index=default_index)
    is_selected_active = (selected_sprint_name == active_sprint_name)

    t_abs = st.tabs(["Sprint leaves", "Sprint holidays"])
    user_role = st.session_state.user.get('user_role', 'Team User')

    # Sprint leaves tab
    with t_abs[0]:
        if user_role != 'Team User' and is_selected_active:
            with st.form("sl_form"):
                st.subheader("Add new leave")
                ca1, ca2 = st.columns(2)
                with ca1:
                    l_sprint = st.selectbox("Sprint", [active_sprint_name], disabled=True, key="leave_sprint_select")
                with ca2:
                    l_name = st.selectbox("Member", team_names, key="leave_member_select")
                l_range = st.date_input("Date range", value=[], key="leave_range_picker")
                l_type = st.selectbox("Type", ["Planned", "Sick", "Emergency"], key="leave_type_select")
                
                if st.form_submit_button("Add leave", type="primary"):
                    if len(l_range) == 2:
                        s_id = active.iloc[0]['id']
                        days = get_workdays(l_range[0], l_range[1])
                        add_leave(l_name, l_type, l_range[0], l_range[1], days, s_id)
                        st.success(f"Leave added for {l_name} in active sprint {active_sprint_name}.")
                        st.rerun()
                    else:
                        st.error("Please select both a start and an end date for the leave range.", icon=":material/error:")
            st.divider()
        elif user_role != 'Team User' and not is_selected_active:
            st.info("Creating new leaves is only allowed for the active sprint.", icon=":material/info:")
        else:
            st.info("Leaves are managed by Team Admins.", icon=":material/info:")

        st.subheader(f"Leaves for '{selected_sprint_name}'")
        leaves_data = get_leaves_with_sprints()
        # Filter leaves by selected sprint
        if not leaves_data.empty:
            leaves_data = leaves_data[leaves_data['sprint'] == selected_sprint_name].copy()
        
        if not leaves_data.empty:
            leaves_display = leaves_data.copy()
            leaves_display['start_date'] = pd.to_datetime(leaves_display['start_date']).dt.date
            leaves_display['end_date'] = pd.to_datetime(leaves_display['end_date']).dt.date
            leaves_display = leaves_display.set_index('id')

            if user_role != 'Team User' and is_selected_active:
                f1, f2 = st.columns([2, 3])
                with f1:
                    member_filter = st.selectbox(
                        "Filter by member",
                        ["All"] + team_names,
                        key="leave_member_filter",
                    )
                with f2:
                    type_filter = st.selectbox(
                        "Filter by type",
                        ["All", "Planned", "Sick", "Emergency"],
                        key="leave_type_filter",
                    )

                filtered_leaves = leaves_data
                if member_filter != "All":
                    filtered_leaves = filtered_leaves[filtered_leaves['name'] == member_filter]
                if type_filter != "All":
                    filtered_leaves = filtered_leaves[filtered_leaves['reason'] == type_filter]

                leaves_edit = filtered_leaves.copy()
                leaves_edit['start_date'] = pd.to_datetime(leaves_edit['start_date']).dt.date
                leaves_edit['end_date'] = pd.to_datetime(leaves_edit['end_date']).dt.date
                leave_id_map = filtered_leaves['id'].values.tolist()
                leaves_edit['Delete'] = False

                def _auto_save_leaves():
                    edited = st.session_state.get("leaves_editor", {}).get("edited_rows", {})
                    if not edited:
                        return
                    for row_idx, changes in edited.items():
                        if "Delete" in changes:
                            continue
                        if row_idx >= len(leave_id_map):
                            continue
                        mongo_id = leave_id_map[row_idx]
                        row = leaves_edit.iloc[row_idx]
                        new_row = {**row.to_dict(), **changes}
                        days = get_workdays(new_row['start_date'], new_row['end_date'])
                        update_leave(mongo_id, new_row['name'], new_row['reason'], new_row['start_date'], new_row['end_date'], days)
                    clear_db_caches()

                st.data_editor(
                    leaves_edit[['name', 'sprint', 'reason', 'start_date', 'end_date', 'total_days', 'Delete']],
                    column_config={
                        "name": st.column_config.SelectboxColumn("Person", options=team_names),
                        "sprint": st.column_config.TextColumn("Sprint", disabled=True),
                        "reason": st.column_config.SelectboxColumn("Type", options=["Planned", "Sick", "Emergency"]),
                        "start_date": st.column_config.DateColumn("Start date"),
                        "end_date": st.column_config.DateColumn("End date"),
                        "total_days": st.column_config.NumberColumn("Days", disabled=True),
                        "Delete": st.column_config.CheckboxColumn("Delete", default=False),
                    },
                    key="leaves_editor",
                    hide_index=True,
                    num_rows="dynamic",
                    on_change=_auto_save_leaves,
                )

                edited_state = st.session_state.get("leaves_editor", {})
                edited_rows = edited_state.get("edited_rows", {})
                delete_marked = [
                    (i, leave_id_map[i])
                    for i, c in edited_rows.items()
                    if c.get("Delete") and i < len(leave_id_map)
                ]
                if delete_marked:
                    names_list = ", ".join(leaves_edit.iloc[i]['name'] for i, _ in delete_marked)
                    st.warning(f"Marked for deletion: **{names_list}**", icon=":material/warning:")
                    if st.button("Confirm delete", type="primary", key="confirm_del_leaves"):
                        deleted = 0
                        for _, mongo_id in delete_marked:
                            delete_leave(mongo_id)
                            deleted += 1
                        if "leaves_editor" in st.session_state:
                            del st.session_state["leaves_editor"]
                        clear_db_caches()
                        st.success(f"Deleted {deleted} leave(s).")
                        st.rerun()
            else:
                st.dataframe(leaves_display[['name', 'sprint', 'reason', 'start_date', 'end_date', 'total_days']], use_container_width=True, hide_index=True)
        else:
            st.info(f"No leaves configured for sprint '{selected_sprint_name}'.", icon=":material/info:")

    # Sprint holidays tab
    with t_abs[1]:
        if user_role != 'Team User' and is_selected_active:
            with st.form("sh_form"):
                st.subheader("Add new holiday")
                ch1, ch2 = st.columns(2)
                with ch1:
                    h_sprint = st.selectbox("Sprint", [active_sprint_name], disabled=True, key="holiday_sprint_select")
                with ch2:
                    h_d = st.date_input("Holiday date", key="holiday_date_picker")
                h_t = st.text_input("Description", key="holiday_desc_input")
                
                if st.form_submit_button("Add holiday", type="primary"):
                    s_id = active.iloc[0]['id']
                    add_holiday(h_d, h_t, s_id)
                    st.success(f"Holiday added for active sprint {active_sprint_name}.")
                    st.rerun()
            st.divider()
        elif user_role != 'Team User' and not is_selected_active:
            st.info("Creating new holidays is only allowed for the active sprint.", icon=":material/info:")
        else:
            st.info("Holidays are managed by Team Admins.", icon=":material/info:")

        st.subheader(f"Holidays for '{selected_sprint_name}'")
        hols_data = get_all_holidays()
        # Filter holidays by selected sprint
        if not hols_data.empty:
            hols_data = hols_data[hols_data['sprint'] == selected_sprint_name].copy()
        
        if not hols_data.empty:
            hols_display = hols_data.copy()
            hols_display['holiday_date'] = pd.to_datetime(hols_display['holiday_date']).dt.date
            hols_display = hols_display.set_index('id')

            if user_role != 'Team User' and is_selected_active:
                hol_search = st.text_input("Search holidays", placeholder="Type to filter by description...", key="hol_search")

                filtered_hols = hols_data
                if hol_search.strip():
                    filtered_hols = filtered_hols[filtered_hols['description'].str.contains(hol_search.strip(), case=False, na=False)]

                hols_edit = filtered_hols.copy()
                hols_edit['holiday_date'] = pd.to_datetime(hols_edit['holiday_date']).dt.date
                hol_id_map = filtered_hols['id'].values.tolist()
                hols_edit['Delete'] = False

                def _auto_save_hols():
                    edited = st.session_state.get("holidays_editor", {}).get("edited_rows", {})
                    if not edited:
                        return
                    for row_idx, changes in edited.items():
                        if "Delete" in changes:
                            continue
                        if row_idx >= len(hol_id_map):
                            continue
                        mongo_id = hol_id_map[row_idx]
                        row = hols_edit.iloc[row_idx]
                        new_row = {**row.to_dict(), **changes}
                        update_holiday(mongo_id, new_row['holiday_date'], new_row['description'])
                    clear_db_caches()

                st.data_editor(
                    hols_edit[['holiday_date', 'description', 'sprint', 'Delete']],
                    column_config={
                        "holiday_date": st.column_config.DateColumn("Holiday date"),
                        "description": "Description",
                        "sprint": st.column_config.TextColumn("Sprint", disabled=True),
                        "Delete": st.column_config.CheckboxColumn("Delete", default=False),
                    },
                    key="holidays_editor",
                    hide_index=True,
                    num_rows="dynamic",
                    on_change=_auto_save_hols,
                )

                edited_state = st.session_state.get("holidays_editor", {})
                edited_rows = edited_state.get("edited_rows", {})
                delete_marked = [
                    (i, hol_id_map[i])
                    for i, c in edited_rows.items()
                    if c.get("Delete") and i < len(hol_id_map)
                ]
                if delete_marked:
                    desc_list = ", ".join(hols_edit.iloc[i]['description'] for i, _ in delete_marked)
                    st.warning(f"Marked for deletion: **{desc_list}**", icon=":material/warning:")
                    if st.button("Confirm delete", type="primary", key="confirm_del_hols"):
                        deleted = 0
                        for _, mongo_id in delete_marked:
                            delete_holiday(mongo_id)
                            deleted += 1
                        if "holidays_editor" in st.session_state:
                            del st.session_state["holidays_editor"]
                        clear_db_caches()
                        st.success(f"Deleted {deleted} holiday(s).")
                        st.rerun()
            else:
                st.dataframe(hols_display[['holiday_date', 'description', 'sprint']], use_container_width=True, hide_index=True)
        else:
            st.info(f"No holidays configured for sprint '{selected_sprint_name}'.", icon=":material/info:")
