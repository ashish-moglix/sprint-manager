import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime, date

# --- APP CONFIG ---
st.set_page_config(page_title="EM Sprint Pro", layout="wide")

# --- DATABASE SETUP ---
conn = sqlite3.connect('sprint_pro_v6.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('CREATE TABLE IF NOT EXISTS team (id INTEGER PRIMARY KEY, name TEXT, role TEXT, daily_sp REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS leaves (id INTEGER PRIMARY KEY, name TEXT, reason TEXT, start_date DATE, end_date DATE, total_days INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS holidays (id INTEGER PRIMARY KEY, holiday_date DATE, description TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS sprints (id INTEGER PRIMARY KEY, name TEXT, start_date DATE, end_date DATE, status TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS backlog (id INTEGER PRIMARY KEY, sprint_id INTEGER, ticket_id TEXT, title TEXT, assignee TEXT, role TEXT, category TEXT, sp REAL)')
    
    c.execute("SELECT COUNT(*) FROM team")
    if c.fetchone()[0] == 0:
        members = [('Partha', 'Backend', 2), ('Kanchan', 'Backend', 2), ('Govind', 'Backend', 2),
                   ('Biswajit', 'Backend', 2), ('Rohit', 'Backend', 2), ('Shashi', 'Frontend', 2),
                   ('Junaid', 'Frontend', 2), ('Kabir', 'Frontend', 2), ('Meenakshi', 'QA', 2),
                   ('Kuldeep', 'QA', 2), ('Ashish', 'Backend', 2)]
        c.executemany("INSERT INTO team (name, role, daily_sp) VALUES (?,?,?)", members)
    conn.commit()

init_db()

# --- HELPERS ---
def get_workdays(start, end):
    try: return len(pd.bdate_range(start, end))
    except: return 0

# --- SESSION STATE FOR EDITING ---
if 'edit_leave_id' not in st.session_state: st.session_state.edit_leave_id = None
if 'edit_member_id' not in st.session_state: st.session_state.edit_member_id = None

# --- SIDEBAR NAV ---
st.sidebar.title("🏢 EM Command")
nav = st.sidebar.radio("NAVIGATION", ["📊 Dashboard", "🎯 Sprint Planning", "📅 Leave & Holidays", "👥 Team Management"])

# --- 1. DASHBOARD ---
if nav == "📊 Dashboard":
    st.title("Sprint Intelligence & Capacity Dashboard")
    active_sprint = pd.read_sql("SELECT * FROM sprints WHERE status='Active'", conn)
    
    if active_sprint.empty:
        st.info("No active sprint. Please start one in 'Team Management'.")
    else:
        s_data = active_sprint.iloc[0]
        s_id, s_start, s_end = s_data['id'], s_data['start_date'], s_data['end_date']
        
        # UI Sliders for Buffers
        with st.sidebar:
            st.subheader("⚙️ Buffer Controls")
            bug_p = st.slider("Prod Bug Buffer (%)", 0, 30, 15)
            adhoc_p = st.slider("Adhoc Buffer (%)", 0, 20, 10)
            ceremony_p = st.slider("Meetings/Ceremonies (%)", 0, 20, 10)

        # Capacity Logic
        workdays = get_workdays(s_start, s_end)
        team = pd.read_sql("SELECT * FROM team", conn)
        leaves = pd.read_sql("SELECT * FROM leaves", conn)
        hols = pd.read_sql(f"SELECT * FROM holidays WHERE holiday_date BETWEEN '{s_start}' AND '{s_end}'", conn)
        
        cap_details = []
        for _, dev in team.iterrows():
            # Personal Leave Calc
            dev_leaves = leaves[leaves['name'] == dev['name']]
            l_days = 0
            for _, l in dev_leaves.iterrows():
                # Overlap calculation
                l_s = max(pd.to_datetime(l['start_date']).date(), pd.to_datetime(s_start).date())
                l_e = min(pd.to_datetime(l['end_date']).date(), pd.to_datetime(s_end).date())
                if l_s <= l_e: l_days += get_workdays(l_s, l_e)
            
            # Net SP = (Workdays - Personal Leaves - Global Holidays) * Daily Rate
            net = (workdays - l_days - len(hols)) * dev['daily_sp']
            cap_details.append({"Name": dev['name'], "Role": dev['role'], "Net SP": net})
        
        cap_df = pd.DataFrame(cap_details)
        total_net = cap_df['Net SP'].sum()
        
        # Strategic Deductions
        bug_b, adhoc_b, meet_b = total_net*(bug_p/100), total_net*(adhoc_p/100), total_net*(ceremony_p/100)
        plannable = total_net - (bug_b + adhoc_b + meet_b)
        
        # Tasks Allocation
        tasks = pd.read_sql(f"SELECT * FROM backlog WHERE sprint_id={s_id}", conn)
        allocated = tasks['sp'].sum() if not tasks.empty else 0
        
        # Metrics Cards
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Net SP", f"{total_net}")
        c2.metric("Buffers (SP)", f"{(bug_b+adhoc_b+meet_b):.1f}")
        c3.metric("Plannable SP", f"{plannable:.1f}")
        c4.metric("Planned", f"{allocated} SP", delta=f"{plannable - allocated:.1f} SP Left")

        st.divider()
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.subheader("Investment Mix (New vs Spillover)")
            if not tasks.empty:
                fig = px.pie(tasks, values='sp', names='category', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
        with col_chart2:
            st.subheader("Load per Role")
            role_summary = cap_df.groupby('Role')['Net SP'].sum().reset_index()
            st.bar_chart(role_summary, x='Role', y='Net SP')

# --- 2. SPRINT PLANNING ---
elif nav == "🎯 Sprint Planning":
    st.title("🎯 Commit Backlog to Sprint")
    sprint = pd.read_sql("SELECT * FROM sprints WHERE status='Active'", conn)
    if not sprint.empty:
        s_id = sprint.iloc[0]['id']
        team_list = pd.read_sql("SELECT name, role FROM team", conn)
        
        with st.form("task_form"):
            col1, col2, col3 = st.columns([1, 2, 1])
            t_id = col1.text_input("Ticket ID (ENG-001)")
            t_title = col2.text_input("Summary")
            t_sp = col3.number_input("SP", value=2.0, step=0.5)
            
            col4, col5 = st.columns(2)
            t_assignee = col4.selectbox("Owner", team_list['name'].tolist())
            t_cat = col5.selectbox("Category", ["New Work", "Spillover", "Bug", "Adhoc"])
            
            if st.form_submit_button("Add Task"):
                t_role = team_list[team_list['name'] == t_assignee]['role'].values[0]
                c.execute("INSERT INTO backlog (sprint_id, ticket_id, title, assignee, role, category, sp) VALUES (?,?,?,?,?,?,?)",
                          (s_id, t_id, t_title, t_assignee, t_role, t_cat, t_sp))
                conn.commit()
                st.rerun()
        
        st.divider()
        st.subheader("Current Sprint Inventory")
        tasks = pd.read_sql(f"SELECT * FROM backlog WHERE sprint_id={s_id}", conn)
        if not tasks.empty:
            for idx, row in tasks.iterrows():
                cx, cy = st.columns([6, 1])
                cx.write(f"**{row['category']}** | {row['ticket_id']} - {row['title']} ({row['assignee']}) | **{row['sp']} SP**")
                if cy.button("Remove", key=f"tk_del_{row['id']}"):
                    c.execute("DELETE FROM backlog WHERE id=?", (row['id'],))
                    conn.commit()
                    st.rerun()

# --- 3. LEAVE & HOLIDAYS ---
elif nav == "📅 Leave & Holidays":
    st.title("Absence & Holiday Management")
    
    t_leave, t_hol = st.tabs(["Employee Leaves", "Global Holidays"])
    
    with t_leave:
        # Edit Leave Logic
        leave_to_edit = None
        if st.session_state.edit_leave_id:
            c.execute("SELECT * FROM leaves WHERE id=?", (st.session_state.edit_leave_id,))
            leave_to_edit = c.fetchone()
        
        with st.form("leave_form"):
            st.subheader("Add / Update Leave")
            names = pd.read_sql("SELECT name FROM team", conn)['name'].tolist()
            l_name = st.selectbox("Member", names, index=names.index(leave_to_edit[1]) if leave_to_edit else 0)
            l_type = st.selectbox("Reason", ["Planned Leave", "Sick Leave", "Emergency Leave"], index=0)
            # Default dates for form
            d_val = [pd.to_datetime(leave_to_edit[3]), pd.to_datetime(leave_to_edit[4])] if leave_to_edit else []
            l_range = st.date_input("Date Range", value=d_val)
            
            if st.form_submit_button("Save Leave Record"):
                if len(l_range) == 2:
                    days = get_workdays(l_range[0], l_range[1])
                    if st.session_state.edit_leave_id:
                        c.execute("UPDATE leaves SET name=?, reason=?, start_date=?, end_date=?, total_days=? WHERE id=?",
                                  (l_name, l_type, l_range[0], l_range[1], days, st.session_state.edit_leave_id))
                        st.session_state.edit_leave_id = None
                    else:
                        c.execute("INSERT INTO leaves (name, reason, start_date, end_date, total_days) VALUES (?,?,?,?,?)",
                                  (l_name, l_type, l_range[0], l_range[1], days))
                    conn.commit()
                    st.rerun()

        st.divider()
        st.subheader("Active Leave Records (Sorted)")
        l_df = pd.read_sql("SELECT * FROM leaves ORDER BY name ASC", conn)
        for _, row in l_df.iterrows():
            c1, c2, c3, c4, c5 = st.columns([2, 3, 1, 1, 1])
            c1.write(f"**{row['name']}**")
            c2.write(f"{row['reason']} ({row['start_date']} to {row['end_date']})")
            c3.write(f"{row['total_days']}d")
            if c4.button("Edit", key=f"le_{row['id']}"):
                st.session_state.edit_leave_id = row['id']
                st.rerun()
            if c5.button("Delete", key=f"ld_{row['id']}"):
                c.execute("DELETE FROM leaves WHERE id=?", (row['id'],))
                conn.commit()
                st.rerun()

    with t_hol:
        with st.form("holiday_form"):
            h_date = st.date_input("Holiday Date")
            h_desc = st.text_input("Description")
            if st.form_submit_button("Add Global Holiday"):
                c.execute("INSERT INTO holidays (holiday_date, description) VALUES (?,?)", (h_date, h_desc))
                conn.commit()
                st.rerun()
        
        h_df = pd.read_sql("SELECT * FROM holidays ORDER BY holiday_date ASC", conn)
        for _, row in h_df.iterrows():
            ca, cb = st.columns([5, 1])
            ca.write(f"📅 {row['holiday_date']} - {row['description']}")
            if cb.button("Delete", key=f"hd_{row['id']}"):
                c.execute("DELETE FROM holidays WHERE id=?", (row['id'],))
                conn.commit()
                st.rerun()

# --- 4. TEAM MANAGEMENT ---
elif nav == "👥 Team Management":
    st.title("Roster & Sprint Control")
    
    tab_team, tab_sprint = st.tabs(["Team Members", "Sprint Setup"])
    
    with tab_team:
        member_to_edit = None
        if st.session_state.edit_member_id:
            c.execute("SELECT * FROM team WHERE id=?", (st.session_state.edit_member_id,))
            member_to_edit = c.fetchone()

        with st.form("team_form"):
            st.subheader("Add / Update Member")
            m_name = st.text_input("Name", value=member_to_edit[1] if member_to_edit else "")
            m_role = st.selectbox("Role", ["Backend", "Frontend", "QA"], index=0)
            m_rate = st.number_input("Daily SP Rate", value=2.0)
            if st.form_submit_button("Save Member"):
                if st.session_state.edit_member_id:
                    c.execute("UPDATE team SET name=?, role=?, daily_sp=? WHERE id=?", (m_name, m_role, m_rate, st.session_state.edit_member_id))
                    st.session_state.edit_member_id = None
                else:
                    c.execute("INSERT INTO team (name, role, daily_sp) VALUES (?,?,?)", (m_name, m_role, m_rate))
                conn.commit()
                st.rerun()
        
        st.divider()
        team_df = pd.read_sql("SELECT * FROM team", conn)
        for _, row in team_df.iterrows():
            col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
            col1.write(f"**{row['name']}**")
            col2.write(row['role'])
            if col3.button("Edit", key=f"tme_{row['id']}"):
                st.session_state.edit_member_id = row['id']
                st.rerun()
            if col4.button("Delete", key=f"tmd_{row['id']}"):
                c.execute("DELETE FROM team WHERE id=?", (row['id'],))
                conn.commit()
                st.rerun()

    with tab_sprint:
        with st.form("sprint_setup"):
            st.subheader("Start New Sprint")
            s_n = st.text_input("Sprint Name (e.g. May Sprint 1)")
            s_dates = st.date_input("Date Range", value=[])
            if st.form_submit_button("Launch Sprint"):
                if len(s_dates) == 2:
                    c.execute("UPDATE sprints SET status='Completed' WHERE status='Active'")
                    c.execute("INSERT INTO sprints (name, start_date, end_date, status) VALUES (?,?,?, 'Active')", (s_n, s_dates[0], s_dates[1]))
                    conn.commit()
                    st.success("Sprint is now LIVE!")
                    st.rerun()
