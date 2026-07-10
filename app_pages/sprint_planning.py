import streamlit as st
import pandas as pd
from datetime import date
from utils.db import (
    get_sprints, get_team, get_leaves, get_holidays, get_backlog,
    add_ticket, update_ticket, delete_ticket
)
from utils.helpers import get_workdays

# Title
st.title("Backlog allocation & tracking")

sprints_df = get_sprints()

if sprints_df.empty:
    st.error("No sprints configured! Create one in Team & System Setup.", icon=":material/error:")
else:
    active = sprints_df[sprints_df['status'] == 'Active']
    active_sprint_name = active.iloc[0]['name'] if not active.empty else None
    active_s_id = active.iloc[0]['id'] if not active.empty else None
    
    team_df = get_team()
    user_role = st.session_state.user.get('user_role', 'Team User')
    user_name = st.session_state.user.get('name')
    is_team_user = (user_role == 'Team User')

    # Sprint Selector at the top
    sprint_names = sprints_df['name'].tolist()
    default_index = sprint_names.index(active_sprint_name) if active_sprint_name in sprint_names else 0
    selected_sprint_name = st.selectbox("Select Sprint to View Backlog", sprint_names, index=default_index)
    selected_s_row = sprints_df[sprints_df['name'] == selected_sprint_name].iloc[0]
    selected_s_id = selected_s_row['id']
    is_selected_active = (selected_sprint_name == active_sprint_name)

    # 1. Add New Ticket Section (Only for active sprint, only if active sprint exists, and only for non-Team Users)
    if not is_team_user:
        if not active.empty:
            with st.container(border=True):
                st.subheader(f"Add new ticket (Adding to active sprint: {active_sprint_name})")
                
                # User input fields
                f1, f2, f3 = st.columns([1, 2, 1])
                with f1:
                    tid = st.text_input("Ticket ID", placeholder="e.g. PROJ-123")
                with f2:
                    title = st.text_input("Title", placeholder="Short task description")
                with f3:
                    sp = st.number_input("Est. SP", min_value=0.0, value=2.0, step=0.5)

                f4, f5 = st.columns(2)
                with f4:
                    owner = st.selectbox("Assignee", team_df['name'].tolist())
                with f5:
                    cat = st.selectbox("Category", ["New Work", "Spillover", "Bug Fix", "Adhoc"])

                # Calculate capacity details for selected dev using active sprint data
                dev_row = team_df[team_df['name'] == owner].iloc[0]
                s_start_dt = pd.to_datetime(active.iloc[0]['start_date'])
                s_end_dt = pd.to_datetime(active.iloc[0]['end_date'])
                wk_days = get_workdays(s_start_dt, s_end_dt)

                hols_in_sprint = len(get_holidays(active_s_id, s_start_dt.date(), s_end_dt.date()))
                leaves_df = get_leaves(active_s_id)
                dev_leaves_sum = leaves_df[(leaves_df['name'] == owner) & (leaves_df['sprint_id'] == active_s_id)]['total_days'].sum()

                eff_days = max(wk_days - hols_in_sprint - dev_leaves_sum, 0)
                dev_role = dev_row.get('role', '')
                daily_sp = 0.0 if dev_role in ['PM', 'EM'] else dev_row['daily_sp']
                total_dev_sp = eff_days * daily_sp
                
                # Buffer calculation from individual developer parameters
                dev_bug_p = dev_row.get('bug_p', 15.0)
                dev_adhoc_p = dev_row.get('adhoc_p', 10.0)
                dev_cere_p = dev_row.get('ceremony_p', 10.0)
                
                dev_buffers = total_dev_sp * (dev_bug_p + dev_adhoc_p + dev_cere_p) / 100
                dev_avail = total_dev_sp - dev_buffers

                backlog_df = get_backlog(active_s_id)
                dev_alloced = backlog_df[backlog_df['assignee'] == owner]['sp'].sum() if not backlog_df.empty else 0.0
                dev_remaining = dev_avail - dev_alloced

                # Live metric cards
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Gross Capacity", f"{total_dev_sp:.1f}")
                m2.metric("Buffers", f"{dev_buffers:.1f}")
                m3.metric("Available", f"{dev_avail:.1f}")
                m4.metric("Allocated", f"{dev_alloced:.1f}")
                m5.metric("Remaining", f"{dev_remaining:.1f}", delta=f"{dev_remaining:+.1f}")

                if st.button("Commit ticket", type="primary"):
                    role = team_df[team_df['name'] == owner]['role'].values[0]
                    add_ticket(active_s_id, tid, title, owner, role, cat, sp)
                    st.success(f"Ticket {tid} added to Active sprint {active_sprint_name}!")
                    st.rerun()
        else:
            st.warning("No sprint is currently active. Sprints must be active to commit new tasks.", icon=":material/warning:")
    else:
        st.info(f"Welcome {user_name}! You can view the backlog and update your own tasks in the active sprint.")

    st.divider()
    tasks = get_backlog(selected_s_id)

    if not tasks.empty:
        if not is_selected_active:
            # Viewing a Draft or Archived Sprint -> Read-only backlog for everyone!
            st.subheader(f"Backlog for '{selected_sprint_name}' (Read-Only - {selected_s_row['status']})")
            tasks_display = tasks[['ticket_id', 'title', 'assignee', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date']].copy()
            tasks_display['sprint'] = selected_sprint_name
            tasks_display['start_date'] = pd.to_datetime(tasks_display['start_date']).dt.date
            tasks_display['end_date'] = pd.to_datetime(tasks_display['end_date']).dt.date
            st.dataframe(tasks_display.set_index('ticket_id'), use_container_width=True)

        elif is_team_user:
            # Active Sprint, Team User role -> Can only edit own tasks
            my_tasks = tasks[tasks['assignee'] == user_name].copy()
            other_tasks = tasks[tasks['assignee'] != user_name].copy()
            
            # 1. Show My Assigned Tasks (Editable)
            st.subheader("My Assigned Tasks (Active Sprint)")
            if not my_tasks.empty:
                my_tasks_display = my_tasks[['id', 'ticket_id', 'title', 'assignee', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date']].copy()
                my_tasks_display['sprint'] = selected_sprint_name
                my_tasks_display['start_date'] = pd.to_datetime(my_tasks_display['start_date']).dt.date
                my_tasks_display['end_date'] = pd.to_datetime(my_tasks_display['end_date']).dt.date
                my_tasks_display['actual_sp'] = my_tasks_display['actual_sp'].fillna(0).astype(float)
                my_tasks_display = my_tasks_display.set_index('id')

                edited_my_tasks = st.data_editor(
                    my_tasks_display,
                    column_config={
                        'sprint': st.column_config.TextColumn('Sprint', width='small', disabled=True),
                        'ticket_id': st.column_config.TextColumn('Ticket', width='small', disabled=True),
                        'title': st.column_config.TextColumn('Title', width='medium', disabled=True),
                        'assignee': st.column_config.TextColumn('Assignee', width='small', disabled=True),
                        'category': st.column_config.TextColumn('Category', width='small', disabled=True),
                        'sp': st.column_config.NumberColumn('Est. SP', min_value=0.0, step=0.5, width='small'),
                        'actual_sp': st.column_config.NumberColumn('Actual SP', min_value=0.0, step=0.5, width='small', disabled=True),
                        'status': st.column_config.SelectboxColumn('Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                        'start_date': st.column_config.DateColumn('Start', width='small'),
                        'end_date': st.column_config.DateColumn('End', width='small'),
                    },
                    key="my_task_editor",
                    height=50 * (len(my_tasks_display) + 1),
                )

                col_save, _ = st.columns([2, 4])
                if col_save.button("Save my changes", type="primary"):
                    for idx, row in edited_my_tasks.iterrows():
                        orig = tasks[tasks['id'] == idx].iloc[0] if idx in tasks['id'].values else None
                        today_str = date.today().isoformat()
                        new_status = row.get('status') or 'Todo'
                        start_str = str(row['start_date']) if pd.notna(row.get('start_date')) else None
                        end_str = str(row['end_date']) if pd.notna(row.get('end_date')) else None

                        if orig is not None:
                            old_status = orig.get('status') or 'Todo'
                            if new_status == 'In Progress' and old_status != 'In Progress' and not start_str:
                                start_str = today_str
                            if new_status == 'Done' and old_status != 'Done' and not end_str:
                                end_str = today_str
                            if new_status == 'Todo' and old_status != 'Todo':
                                start_str = None
                                end_str = None

                            update_ticket(
                                idx, orig['ticket_id'], orig['title'], orig['assignee'], orig['category'],
                                float(row['sp']), float(orig.get('actual_sp') or 0.0), new_status, start_str, end_str
                            )
                    st.rerun()
            else:
                st.info("You currently have no tasks assigned to you in this sprint.")
            
            # 2. Show Other Tasks (Read-Only)
            if not other_tasks.empty:
                st.subheader("Team's Backlog (Read-Only)")
                other_display = other_tasks[['ticket_id', 'title', 'assignee', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date']].copy()
                other_display['sprint'] = selected_sprint_name
                other_display['start_date'] = pd.to_datetime(other_display['start_date']).dt.date
                other_display['end_date'] = pd.to_datetime(other_display['end_date']).dt.date
                other_display['actual_sp'] = other_display['actual_sp'].fillna(0).astype(float)
                st.dataframe(other_display.set_index('ticket_id'), use_container_width=True)

        else:
            # Active Sprint, Scrum Master/Admin/PM role -> Full edit privileges!
            st.subheader("Task tracker (Active Sprint)")
            tasks_display = tasks[['id', 'ticket_id', 'title', 'assignee', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date']].copy()
            tasks_display['sprint'] = selected_sprint_name
            tasks_display['start_date'] = pd.to_datetime(tasks_display['start_date']).dt.date
            tasks_display['end_date'] = pd.to_datetime(tasks_display['end_date']).dt.date
            tasks_display['actual_sp'] = tasks_display['actual_sp'].fillna(0).astype(float)
            tasks_display = tasks_display.set_index('id')

            edited_tasks = st.data_editor(
                tasks_display,
                column_config={
                    'sprint': st.column_config.TextColumn('Sprint', width='small', disabled=True),
                    'ticket_id': st.column_config.TextColumn('Ticket', width='small'),
                    'title': st.column_config.TextColumn('Title', width='medium'),
                    'assignee': st.column_config.SelectboxColumn('Assignee', options=team_df['name'].tolist(), width='small'),
                    'category': st.column_config.SelectboxColumn('Category', options=['New Work', 'Spillover', 'Bug Fix', 'Adhoc'], width='small'),
                    'sp': st.column_config.NumberColumn('Est. SP', min_value=0.0, step=0.5, width='small'),
                    'actual_sp': st.column_config.NumberColumn('Actual SP', min_value=0.0, step=0.5, width='small'),
                    'status': st.column_config.SelectboxColumn('Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                    'start_date': st.column_config.DateColumn('Start', width='small'),
                    'end_date': st.column_config.DateColumn('End', width='small'),
                },
                key="task_editor",
                height=50 * (len(tasks_display) + 1),
            )

            col_save, _ = st.columns([2, 4])
            if col_save.button("Save all changes", type="primary"):
                for idx, row in edited_tasks.iterrows():
                    orig = tasks[tasks['id'] == idx].iloc[0] if idx in tasks['id'].values else None
                    today_str = date.today().isoformat()
                    new_status = row.get('status') or 'Todo'
                    start_str = str(row['start_date']) if pd.notna(row.get('start_date')) else None
                    end_str = str(row['end_date']) if pd.notna(row.get('end_date')) else None

                    if orig is not None:
                        old_status = orig.get('status') or 'Todo'
                        if new_status == 'In Progress' and old_status != 'In Progress' and not start_str:
                            start_str = today_str
                        if new_status == 'Done' and old_status != 'Done' and not end_str:
                            end_str = today_str
                        if new_status == 'Todo' and old_status != 'Todo':
                            start_str = None
                            end_str = None

                    update_ticket(
                        idx, row['ticket_id'], row['title'], row['assignee'], row['category'],
                        float(row['sp']), float(row.get('actual_sp') or 0.0), new_status, start_str, end_str
                    )
                st.rerun()

            st.subheader("Delete task")
            del_task_id = st.selectbox("Select task to delete", [""] + tasks['ticket_id'].tolist())
            if del_task_id and st.button("Delete task", type="primary"):
                delete_ticket(del_task_id)
                st.rerun()

        st.divider()
        st.subheader("Sprint velocity summary")
        total_est = tasks['sp'].sum()
        total_act = tasks['actual_sp'].fillna(0).sum()
        variance = total_act - total_est

        ks = st.columns(4, border=True)
        ks[0].metric("Total Est. SP", f"{total_est:.1f}")
        ks[1].metric("Total Actual SP", f"{total_act:.1f}", delta=f"{variance:.1f}")
        ks[2].metric("Variance", f"{variance:+.1f} SP", delta_color="inverse")
        pct = (total_act / total_est * 100 - 100) if total_est > 0 else 0
        ks[3].metric("Swing", f"{pct:+.0f}%", delta_color="inverse")

        done = tasks[tasks['status'] == 'Done'] if 'status' in tasks.columns else pd.DataFrame()
        if not done.empty:
            done2 = done.copy()
            done2['Duration'] = done2.apply(
                lambda r: (pd.to_datetime(r['end_date']) - pd.to_datetime(r['start_date'])).days
                if r.get('end_date') and r.get('start_date') else None, axis=1)
            done2['SP/Day'] = done2.apply(
                lambda r: round((r.get('actual_sp') or r['sp']) / max(r['Duration'], 1), 2)
                if r.get('Duration') else None, axis=1)
            detail = done2.groupby('assignee').agg(
                Tasks=('ticket_id', 'count'),
                Est_SP=('sp', 'sum'),
                Actual_SP=('actual_sp', 'sum'),
                Avg_Days=('Duration', 'mean'),
            ).reset_index()
            detail['Avg_SP/Day'] = (detail['Actual_SP'] / detail['Avg_Days']).round(2)
            detail['Avg_Days'] = detail['Avg_Days'].round(1)
            detail.columns = ['Assignee', 'Done Tickets', 'Total Est. SP', 'Total Actual SP', 'Avg Days/Ticket', 'Avg SP/Day']
            st.dataframe(detail, hide_index=True)
