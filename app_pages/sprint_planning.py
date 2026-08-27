import streamlit as st
import pandas as pd
from datetime import date
from utils.db import (
    get_sprints, get_team, get_leaves, get_holidays, get_backlog,
    add_ticket, update_ticket, delete_ticket, clear_db_caches,
    get_current_team_jira_config, add_ticket_comment, get_ticket_comments
)
from utils.helpers import get_workdays


def _calc_actual_sp(start_date_val, end_date_val):
    """Return actual SP = workdays × 2 SP/day. Both start and end are counted, weekends excluded."""
    try:
        if not start_date_val or not end_date_val:
            return None
        start = pd.to_datetime(start_date_val).date() if not isinstance(start_date_val, date) else start_date_val
        end = pd.to_datetime(end_date_val).date() if not isinstance(end_date_val, date) else end_date_val
        if pd.isna(start) or pd.isna(end):
            return None
        workdays = get_workdays(start, end)
        return round(workdays * 2, 2)
    except Exception:
        return None

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

    # JIRA Sync Section
    jira_cfg = get_current_team_jira_config()
    if jira_cfg and jira_cfg.get("board_id"):
        with st.container(border=True):
            st.subheader("JIRA Sync")
            c_sync, c_info = st.columns([1, 3])
            with c_sync:
                if st.button("Sync from JIRA", help="Fetch new tickets from JIRA board"):
                    from utils.jira_sync import sync_sprint_from_jira
                    with st.spinner("Syncing from JIRA..."):
                        result = sync_sprint_from_jira(
                            selected_s_id, selected_sprint_name,
                            jira_cfg["board_id"], jira_cfg.get("url", "")
                        )
                    if result.get("error"):
                        st.warning(result["error"])
                    elif result["added"] > 0:
                        st.success(f"Added {result['added']} new ticket(s) from JIRA. {result['skipped']} already existed.")
                        st.rerun()
                    else:
                        st.info("No new tickets found in JIRA. All tickets already synced.")
            with c_info:
                st.caption(f"Board ID: {jira_cfg['board_id']} | Syncs tickets from JIRA sprint '{selected_sprint_name}'")

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
                s_start_dt = pd.to_datetime(active.iloc[0]['start_date'], format='mixed')
                s_end_dt = pd.to_datetime(active.iloc[0]['end_date'], format='mixed')
                wk_days = get_workdays(s_start_dt.date(), s_end_dt.date())

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
    has_jira_col = "jira_url" in tasks.columns and tasks["jira_url"].notna().any()

    if not tasks.empty:
        if not is_selected_active:
            st.subheader(f"Backlog for '{selected_sprint_name}' (Read-Only - {selected_s_row['status']})")
            tasks_display = tasks[['ticket_id', 'title', 'assignee', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date',
                                   'backend_assignee', 'frontend_assignee', 'qa_assignee',
                                   'backend_sp', 'frontend_sp', 'qa_sp',
                                   'backend_start_date', 'backend_end_date',
                                   'frontend_start_date', 'frontend_end_date',
                                   'qa_start_date', 'qa_end_date',
                                   'backend_status', 'frontend_status', 'qa_status']].copy()
            # Calculate total dev SP and estimated SP
            tasks_display['backend_sp'] = tasks_display['backend_sp'].fillna(0).astype(float)
            tasks_display['frontend_sp'] = tasks_display['frontend_sp'].fillna(0).astype(float)
            tasks_display['qa_sp'] = tasks_display['qa_sp'].fillna(0).astype(float)
            tasks_display['total_dev_sp'] = tasks_display['backend_sp'] + tasks_display['frontend_sp']
            tasks_display['est_sp'] = tasks_display['total_dev_sp'] + tasks_display['qa_sp']

            if has_jira_col:
                tasks_display['jira_url'] = tasks['jira_url']
            tasks_display['sprint'] = selected_sprint_name
            for col in ['start_date', 'end_date', 'backend_start_date', 'backend_end_date',
                        'frontend_start_date', 'frontend_end_date', 'qa_start_date', 'qa_end_date']:
                if col in tasks_display.columns:
                    tasks_display[col] = pd.to_datetime(tasks_display[col], format='mixed', errors='coerce').dt.date
            tasks_display['actual_sp'] = tasks_display['actual_sp'].fillna(0).astype(float)
            col_config = {'sprint': st.column_config.TextColumn('Sprint', width='small', disabled=True)}
            if has_jira_col:
                col_config['jira_url'] = st.column_config.LinkColumn('JIRA', width='small', display_text='Open')
            st.dataframe(tasks_display.set_index('ticket_id'), use_container_width=True, column_config=col_config)

        elif is_team_user:
            # Active Sprint, Team User role -> Can only edit own tasks
            my_tasks = tasks[tasks['assignee'] == user_name].copy()
            other_tasks = tasks[tasks['assignee'] != user_name].copy()
            
            # 1. Show My Assigned Tasks (Editable)
            st.subheader("My Assigned Tasks (Active Sprint)")
            if not my_tasks.empty:
                my_tasks_display = my_tasks[['ticket_id', 'title', 'status', 'backend_status', 'frontend_status', 'qa_status',
                                              'sp', 'backend_sp', 'frontend_sp', 'qa_sp', 'actual_sp',
                                              'start_date', 'end_date',
                                              'backend_start_date', 'backend_end_date',
                                              'frontend_start_date', 'frontend_end_date',
                                              'qa_start_date', 'qa_end_date']].copy()
                if has_jira_col:
                    my_tasks_display['jira_url'] = my_tasks['jira_url']
                my_tasks_display['sprint'] = selected_sprint_name
                my_tasks_display['actual_sp'] = my_tasks_display['actual_sp'].fillna(0).astype(float)
                my_tasks_display = my_tasks_display.set_index('id')

                my_col_config={
                    'sprint': st.column_config.TextColumn('Sprint', width='small', disabled=True),
                    'ticket_id': st.column_config.TextColumn('Ticket', width='small', disabled=True),
                    'title': st.column_config.TextColumn('Title', width='medium', disabled=True),
                    'status': st.column_config.SelectboxColumn('Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                    'backend_status': st.column_config.SelectboxColumn('Backend Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                    'frontend_status': st.column_config.SelectboxColumn('Frontend Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                    'qa_status': st.column_config.SelectboxColumn('QA Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                    'sp': st.column_config.NumberColumn('Est. SP', min_value=0.0, step=0.5, width='small'),
                    'backend_sp': st.column_config.NumberColumn('Backend SP', min_value=0.0, step=0.5, width='small'),
                    'frontend_sp': st.column_config.NumberColumn('Frontend SP', min_value=0.0, step=0.5, width='small'),
                    'qa_sp': st.column_config.NumberColumn('QA SP', min_value=0.0, step=0.5, width='small'),
                    'actual_sp': st.column_config.NumberColumn('Actual SP', min_value=0.0, step=0.5, width='small', disabled=True),
                    'start_date': st.column_config.DateColumn('Start', width='small'),
                    'end_date': st.column_config.DateColumn('End', width='small'),
                    'backend_start_date': st.column_config.DateColumn('Backend Start', width='small'),
                    'backend_end_date': st.column_config.DateColumn('Backend End', width='small'),
                    'frontend_start_date': st.column_config.DateColumn('Frontend Start', width='small'),
                    'frontend_end_date': st.column_config.DateColumn('Frontend End', width='small'),
                    'qa_start_date': st.column_config.DateColumn('QA Start', width='small'),
                    'qa_end_date': st.column_config.DateColumn('QA End', width='small'),
                }
                if has_jira_col:
                    my_col_config['jira_url'] = st.column_config.LinkColumn('JIRA', width='small', display_text='Open')

                edited_my_tasks = st.data_editor(
                    my_tasks_display,
                    column_config=my_col_config,
                    key="my_task_editor",
                    hide_index=True,
                    num_rows="dynamic",
                    use_container_width=True,
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

                            computed_sp = _calc_actual_sp(start_str, end_str)
                            actual_sp_val = computed_sp if computed_sp is not None else float(orig.get('actual_sp') or 0.0)
                            update_ticket(
                                idx, orig['ticket_id'], orig['title'], orig['assignee'], orig['category'],
                                float(row['sp']), actual_sp_val, new_status, start_str, end_str,
                                backend_assignee=row.get('backend_assignee'),
                                frontend_assignee=row.get('frontend_assignee'),
                                qa_assignee=row.get('qa_assignee'),
                                backend_sp=float(row.get('backend_sp') or 0),
                                frontend_sp=float(row.get('frontend_sp') or 0),
                                qa_sp=float(row.get('qa_sp') or 0),
                                backend_status=row.get('backend_status'),
                                frontend_status=row.get('frontend_status'),
                                qa_status=row.get('qa_status'),
                            )
                    if "my_task_editor" in st.session_state:
                        del st.session_state["my_task_editor"]
                    st.rerun()
            else:
                st.info("You currently have no tasks assigned to you in this sprint.")
            
            # 2. Show Other Tasks (Read-Only)
            if not other_tasks.empty:
                st.subheader("Team's Backlog (Read-Only)")
                other_display = other_tasks[['ticket_id', 'title', 'assignee', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date',
                                              'backend_assignee', 'frontend_assignee', 'qa_assignee',
                                              'backend_sp', 'frontend_sp', 'qa_sp',
                                              'backend_start_date', 'backend_end_date',
                                              'frontend_start_date', 'frontend_end_date',
                                              'qa_start_date', 'qa_end_date',
                                              'backend_status', 'frontend_status', 'qa_status']].copy()
                if has_jira_col:
                    other_display['jira_url'] = other_tasks['jira_url']
                other_display['sprint'] = selected_sprint_name
                other_display['backend_sp'] = other_display['backend_sp'].fillna(0).astype(float)
                other_display['frontend_sp'] = other_display['frontend_sp'].fillna(0).astype(float)
                other_display['qa_sp'] = other_display['qa_sp'].fillna(0).astype(float)
                other_display['total_dev_sp'] = other_display['backend_sp'] + other_display['frontend_sp']
                other_display['est_sp'] = other_display['total_dev_sp'] + other_display['qa_sp']
                for col in ['start_date', 'end_date', 'backend_start_date', 'backend_end_date',
                            'frontend_start_date', 'frontend_end_date', 'qa_start_date', 'qa_end_date']:
                    if col in other_display.columns:
                        other_display[col] = pd.to_datetime(other_display[col], format='mixed', errors='coerce').dt.date
                other_display['actual_sp'] = other_display['actual_sp'].fillna(0).astype(float)
                other_col_config = {}
                if has_jira_col:
                    other_col_config['jira_url'] = st.column_config.LinkColumn('JIRA', width='small', display_text='Open')
                st.dataframe(other_display.set_index('ticket_id'), use_container_width=True, column_config=other_col_config)

        else:
            # Active Sprint, Scrum Master/Admin/PM role -> Full edit privileges!
            st.subheader("Task tracker (Active Sprint)")

            f1, f2 = st.columns([2, 3])
            with f1:
                assignee_filter = st.selectbox(
                    "Filter by assignee",
                    ["All"] + team_df['name'].tolist(),
                    key="assignee_filter",
                )
            with f2:
                title_search = st.text_input("Search by title", placeholder="Type to filter tasks...", key="title_search")

            filtered_tasks = tasks
            if assignee_filter != "All":
                # Filter by any assignee field (main, backend, frontend, qa)
                mask = (
                    (filtered_tasks['assignee'] == assignee_filter) |
                    (filtered_tasks['backend_assignee'] == assignee_filter) |
                    (filtered_tasks['frontend_assignee'] == assignee_filter) |
                    (filtered_tasks['qa_assignee'] == assignee_filter)
                )
                filtered_tasks = filtered_tasks[mask]
            if title_search.strip():
                filtered_tasks = filtered_tasks[filtered_tasks['title'].str.contains(title_search.strip(), case=False, na=False)]

            # Reorder columns for better visibility
            tasks_display = filtered_tasks[['ticket_id', 'title', 'assignee', 'category',
                                             'status', 'backend_status', 'frontend_status', 'qa_status',
                                             'sp', 'backend_sp', 'frontend_sp', 'qa_sp', 'actual_sp',
                                             'start_date', 'end_date',
                                             'backend_start_date', 'backend_end_date',
                                             'frontend_start_date', 'frontend_end_date',
                                             'qa_start_date', 'qa_end_date',
                                             'backend_assignee', 'frontend_assignee', 'qa_assignee']].copy()
            if has_jira_col:
                tasks_display['jira_url'] = filtered_tasks['jira_url']
                tasks_display['jira_push_status'] = filtered_tasks.get('jira_push_status', None)
            tasks_display['sprint'] = selected_sprint_name
            tasks_display['start_date'] = pd.to_datetime(tasks_display['start_date'], format='mixed').dt.date
            tasks_display['end_date'] = pd.to_datetime(tasks_display['end_date'], format='mixed').dt.date
            tasks_display['actual_sp'] = tasks_display['actual_sp'].fillna(0).astype(float)
            tasks_display['_id'] = filtered_tasks['id'].values
            tasks_display['Delete'] = False

            def _auto_save():
                edited = st.session_state.get("task_editor", {}).get("edited_rows", {})
                if not edited:
                    return
                for row_idx, changes in edited.items():
                    if "Delete" in changes:
                        continue
                    row = tasks_display.iloc[row_idx]
                    mongo_id = row['_id']
                    new_row = {**row.to_dict(), **changes}
                    orig = tasks[tasks['id'] == mongo_id].iloc[0] if mongo_id in tasks['id'].values else None
                    today_str = date.today().isoformat()
                    new_status = new_row.get('status') or 'Todo'
                    start_str = str(new_row['start_date']) if pd.notna(new_row.get('start_date')) else None
                    end_str = str(new_row['end_date']) if pd.notna(new_row.get('end_date')) else None
                    if orig is not None:
                        old_status = orig.get('status') or 'Todo'
                        if new_status == 'In Progress' and old_status != 'In Progress' and not start_str:
                            start_str = today_str
                        if new_status == 'Done' and old_status != 'Done' and not end_str:
                            end_str = today_str
                        if new_status == 'Todo' and old_status != 'Todo':
                            start_str = None
                            end_str = None
                    computed_sp = _calc_actual_sp(start_str, end_str)
                    actual_sp_val = computed_sp if computed_sp is not None else float(new_row.get('actual_sp') or 0.0)
                    update_ticket(
                        mongo_id, new_row['ticket_id'], new_row['title'], new_row['assignee'],
                        new_row['category'], float(new_row['sp']), actual_sp_val,
                        new_status, start_str, end_str,
                        backend_assignee=new_row.get('backend_assignee'),
                        frontend_assignee=new_row.get('frontend_assignee'),
                        qa_assignee=new_row.get('qa_assignee'),
                        backend_sp=float(new_row.get('backend_sp') or 0),
                        frontend_sp=float(new_row.get('frontend_sp') or 0),
                        qa_sp=float(new_row.get('qa_sp') or 0),
                        backend_status=new_row.get('backend_status'),
                        frontend_status=new_row.get('frontend_status'),
                        qa_status=new_row.get('qa_status'),
                    )
                clear_db_caches()

            admin_col_config={
                'sprint': st.column_config.TextColumn('Sprint', width='small', disabled=True),
                'ticket_id': st.column_config.TextColumn('Ticket', width='small'),
                'title': st.column_config.TextColumn('Title', width='medium'),
                'assignee': st.column_config.SelectboxColumn('Assignee', options=team_df['name'].tolist(), width='small'),
                'category': st.column_config.SelectboxColumn('Category', options=['New Work', 'Spillover', 'Bug Fix', 'Adhoc'], width='small'),
                'status': st.column_config.SelectboxColumn('Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                'backend_status': st.column_config.SelectboxColumn('Backend Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                'frontend_status': st.column_config.SelectboxColumn('Frontend Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                'qa_status': st.column_config.SelectboxColumn('QA Status', options=['Todo', 'In Progress', 'Done'], width='small'),
                'sp': st.column_config.NumberColumn('Est. SP', min_value=0.0, step=0.5, width='small'),
                'backend_sp': st.column_config.NumberColumn('Backend SP', min_value=0.0, step=0.5, width='small'),
                'frontend_sp': st.column_config.NumberColumn('Frontend SP', min_value=0.0, step=0.5, width='small'),
                'qa_sp': st.column_config.NumberColumn('QA SP', min_value=0.0, step=0.5, width='small'),
                'actual_sp': st.column_config.NumberColumn('Actual SP', min_value=0.0, step=0.5, width='small', disabled=True),
                'start_date': st.column_config.DateColumn('Start', width='small'),
                'end_date': st.column_config.DateColumn('End', width='small'),
                'backend_start_date': st.column_config.DateColumn('Backend Start', width='small'),
                'backend_end_date': st.column_config.DateColumn('Backend End', width='small'),
                'frontend_start_date': st.column_config.DateColumn('Frontend Start', width='small'),
                'frontend_end_date': st.column_config.DateColumn('Frontend End', width='small'),
                'qa_start_date': st.column_config.DateColumn('QA Start', width='small'),
                'qa_end_date': st.column_config.DateColumn('QA End', width='small'),
                'backend_assignee': st.column_config.SelectboxColumn('Backend Assignee', options=team_df['name'].tolist(), width='small'),
                'frontend_assignee': st.column_config.SelectboxColumn('Frontend Assignee', options=team_df['name'].tolist(), width='small'),
                'qa_assignee': st.column_config.SelectboxColumn('QA Assignee', options=team_df['name'].tolist(), width='small'),
                'Delete': st.column_config.CheckboxColumn('Delete', default=False),
                '_id': None,
            }
            if has_jira_col:
                admin_col_config['jira_url'] = st.column_config.LinkColumn('JIRA', width='small', display_text='Open')
                admin_col_config['jira_push_status'] = st.column_config.TextColumn('Sync', width='small', disabled=True)

            st.data_editor(
                tasks_display,
                column_config=admin_col_config,
                key="task_editor",
                hide_index=True,
                num_rows="dynamic",
                use_container_width=True,
                disabled=['sprint', 'ticket_id', 'title', 'assignee', 'category', 'actual_sp'],
                on_change=_auto_save,
            )

            edited_state = st.session_state.get("task_editor", {})
            edited_rows = edited_state.get("edited_rows", {})
            current_data = edited_state.get("data", tasks_display)
            delete_marked = [
                (i, current_data.iloc[i])
                for i, c in edited_rows.items()
                if c.get("Delete") and i < len(current_data)
            ]
            if delete_marked:
                ticket_list = ", ".join(r['ticket_id'] or r['title'] for _, r in delete_marked)
                st.warning(f"Marked for deletion: **{ticket_list}**", icon=":material/warning:")
                if st.button("Confirm delete", type="primary", key="confirm_del"):
                    deleted = 0
                    for _, row in delete_marked:
                        delete_ticket(row['ticket_id'])
                        deleted += 1
                    if "task_editor" in st.session_state:
                        del st.session_state["task_editor"]
                    clear_db_caches()
                    st.success(f"Deleted {deleted} task(s).")
                    st.rerun()

            # Push to JIRA section - hidden until field mapping is finalized
            # TODO: Re-enable once we have all field IDs (start date, end date, actual SP) configured
            # if has_jira_col and jira_cfg:
            #     st.divider()
            #     st.subheader("Push to JIRA")
            #     ... (push buttons and comments expander hidden for now)

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
                lambda r: (pd.to_datetime(r['end_date'], format='mixed') - pd.to_datetime(r['start_date'], format='mixed')).days
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
