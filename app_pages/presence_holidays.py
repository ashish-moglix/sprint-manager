import streamlit as st
import pandas as pd
from utils.db import (
    get_sprints, get_team, get_leaves_with_sprints, get_all_holidays,
    add_leave, update_leave, delete_leave, add_holiday, update_holiday, delete_holiday
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
    t_abs = st.tabs(["Sprint leaves", "Sprint holidays"])

    # Sprint leaves tab
    with t_abs[0]:
        with st.form("sl_form"):
            st.subheader("Add new leave")
            ca1, ca2 = st.columns(2)
            with ca1:
                l_sprint = st.selectbox("Sprint", sprints_df['name'].tolist(), key="leave_sprint_select")
            with ca2:
                l_name = st.selectbox("Member", team_names, key="leave_member_select")
            l_range = st.date_input("Date range", value=[], key="leave_range_picker")
            l_type = st.selectbox("Type", ["Planned", "Sick", "Emergency"], key="leave_type_select")
            
            if st.form_submit_button("Add leave", type="primary"):
                if len(l_range) == 2:
                    s_id = sprints_df[sprints_df['name'] == l_sprint]['id'].values[0]
                    days = get_workdays(l_range[0], l_range[1])
                    add_leave(l_name, l_type, l_range[0], l_range[1], days, s_id)
                    st.rerun()
                else:
                    st.error("Please select both a start and an end date for the leave range.", icon=":material/error:")

        st.divider()
        st.subheader("All leaves")
        leaves_data = get_leaves_with_sprints()
        
        if not leaves_data.empty:
            leaves_display = leaves_data.copy()
            leaves_display['start_date'] = pd.to_datetime(leaves_display['start_date']).dt.date
            leaves_display['end_date'] = pd.to_datetime(leaves_display['end_date']).dt.date
            leaves_display = leaves_display.set_index('id')

            edited = st.data_editor(
                leaves_display,
                column_config={
                    "name": st.column_config.SelectboxColumn("Person", options=team_names),
                    "sprint": st.column_config.TextColumn("Sprint", disabled=True),
                    "reason": st.column_config.SelectboxColumn("Type", options=["Planned", "Sick", "Emergency"]),
                    "start_date": st.column_config.DateColumn("Start date"),
                    "end_date": st.column_config.DateColumn("End date"),
                    "total_days": st.column_config.NumberColumn("Days", disabled=True),
                },
                key="leaves_editor",
            )

            col_save, _ = st.columns([2, 4])
            if col_save.button("Save leave changes", type="primary"):
                for idx, row in edited.iterrows():
                    days = get_workdays(row['start_date'], row['end_date'])
                    update_leave(idx, row['name'], row['reason'], row['start_date'], row['end_date'], days)
                st.rerun()

            st.subheader("Delete leaves")
            del_leave = st.selectbox("Select leave entry to delete", [""] + leaves_data['id'].astype(str).tolist(), key="delete_leave_select")
            if del_leave and st.button("Delete selected leave", type="primary", key="delete_leave_btn"):
                delete_leave(del_leave)
                st.rerun()
        else:
            st.info("No leaves configured.", icon=":material/info:")

    # Sprint holidays tab
    with t_abs[1]:
        with st.form("sh_form"):
            st.subheader("Add new holiday")
            ch1, ch2 = st.columns(2)
            with ch1:
                h_sprint = st.selectbox("Sprint", sprints_df['name'].tolist(), key="holiday_sprint_select")
            with ch2:
                h_d = st.date_input("Holiday date", key="holiday_date_picker")
            h_t = st.text_input("Description", key="holiday_desc_input")
            
            if st.form_submit_button("Add holiday", type="primary"):
                s_id = sprints_df[sprints_df['name'] == h_sprint]['id'].values[0]
                add_holiday(h_d, h_t, s_id)
                st.rerun()

        st.divider()
        st.subheader("All holidays")
        hols_data = get_all_holidays()
        
        if not hols_data.empty:
            hols_display = hols_data.copy()
            hols_display['holiday_date'] = pd.to_datetime(hols_display['holiday_date']).dt.date
            hols_display = hols_display.set_index('id')

            edited_h = st.data_editor(
                hols_display,
                column_config={
                    "holiday_date": st.column_config.DateColumn("Holiday date"),
                    "description": "Description",
                    "sprint": st.column_config.TextColumn("Sprint", disabled=True),
                },
                key="holidays_editor",
            )

            col_save2, _ = st.columns([2, 4])
            if col_save2.button("Save holiday changes", type="primary"):
                for idx, row in edited_h.iterrows():
                    update_holiday(idx, row['holiday_date'], row['description'])
                st.rerun()

            st.subheader("Delete holidays")
            del_hol = st.selectbox("Select holiday to delete", [""] + hols_data['id'].astype(str).tolist(), key="delete_holiday_select")
            if del_hol and st.button("Delete selected holiday", type="primary", key="delete_holiday_btn"):
                delete_holiday(del_hol)
                st.rerun()
        else:
            st.info("No holidays configured.", icon=":material/info:")
