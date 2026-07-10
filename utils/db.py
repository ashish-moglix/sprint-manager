import sqlite3
import pandas as pd
import streamlit as st

DB_NAME = 'em_v10_final.db'

def get_connection():
    """Get connection to SQLite database."""
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    """Initialize database tables and default team members."""
    conn = get_connection()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS team (id INTEGER PRIMARY KEY, name TEXT, role TEXT, daily_sp REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS sprints (id INTEGER PRIMARY KEY, name TEXT, start_date DATE, end_date DATE, status TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS backlog (id INTEGER PRIMARY KEY, sprint_id INTEGER, ticket_id TEXT, title TEXT, assignee TEXT, role TEXT, category TEXT, sp REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS leaves (id INTEGER PRIMARY KEY, name TEXT, reason TEXT, start_date DATE, end_date DATE, total_days INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS holidays (id INTEGER PRIMARY KEY, holiday_date DATE, description TEXT)')

    for col, dtype in [('start_date', 'DATE'), ('end_date', 'DATE'), ("status", "TEXT DEFAULT 'Todo'")]:
        try:
            c.execute(f"ALTER TABLE backlog ADD COLUMN {col} {dtype}")
        except sqlite3.OperationalError:
            pass

    try:
        c.execute("ALTER TABLE leaves ADD COLUMN sprint_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE holidays ADD COLUMN sprint_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE backlog ADD COLUMN actual_sp REAL")
    except sqlite3.OperationalError:
        pass

    c.execute("SELECT COUNT(*) FROM team")
    if c.fetchone()[0] == 0:
        members = [
            ('Partha', 'Backend', 2.0), ('Kanchan', 'Backend', 2.0), ('Govind', 'Backend', 2.0),
            ('Biswajit', 'Backend', 2.0), ('Rohit', 'Backend', 2.0), ('Shashi', 'Frontend', 2.0),
            ('Junaid', 'Frontend', 2.0), ('Kabir', 'Frontend', 2.0), ('Meenakshi', 'QA', 2.0),
            ('Kuldeep', 'QA', 2.0), ('Ashish', 'Backend', 2.0)
        ]
        c.executemany("INSERT INTO team (name, role, daily_sp) VALUES (?,?,?)", members)
    conn.commit()
    conn.close()

# --- CACHED READ OPERATIONS ---

@st.cache_data(ttl="15m")
def get_sprints():
    """Load all sprints from the database."""
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM sprints ORDER BY id DESC", conn)
    conn.close()
    return df

@st.cache_data(ttl="15m")
def get_team():
    """Load the full team roster."""
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM team", conn)
    conn.close()
    return df

@st.cache_data(ttl="15m")
def get_leaves(sprint_id):
    """Load leaves related to a specific sprint or global ones."""
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM leaves WHERE sprint_id={sprint_id} OR sprint_id=0", conn)
    conn.close()
    return df

@st.cache_data(ttl="15m")
def get_leaves_with_sprints():
    """Load all leaves along with sprint name."""
    conn = get_connection()
    df = pd.read_sql("""
        SELECT l.id, l.name, s.name as sprint, l.reason, l.start_date, l.end_date, l.total_days
        FROM leaves l
        LEFT JOIN sprints s ON l.sprint_id = s.id
        ORDER BY l.sprint_id DESC, l.name
    """, conn)
    conn.close()
    return df

@st.cache_data(ttl="15m")
def get_holidays(sprint_id, s_start, s_end):
    """Load holidays that fall within a sprint range."""
    conn = get_connection()
    query = f"SELECT * FROM holidays WHERE sprint_id={sprint_id} AND holiday_date BETWEEN '{s_start}' AND '{s_end}'"
    df = pd.read_sql(query, conn)
    conn.close()
    return df

@st.cache_data(ttl="15m")
def get_all_holidays():
    """Load all holidays along with sprint name."""
    conn = get_connection()
    df = pd.read_sql("""
        SELECT h.id, h.holiday_date, h.description, s.name as sprint
        FROM holidays h
        LEFT JOIN sprints s ON h.sprint_id = s.id
        ORDER BY h.holiday_date
    """, conn)
    conn.close()
    return df

@st.cache_data(ttl="15m")
def get_backlog(sprint_id):
    """Load backlog tickets for a specific sprint."""
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM backlog WHERE sprint_id={sprint_id}", conn)
    conn.close()
    return df

# --- MUTATION OPERATIONS (Mutate database and clear cache) ---

def clear_db_caches():
    """Invalidate all cached read operations."""
    st.cache_data.clear()

def add_ticket(sprint_id, ticket_id, title, assignee, role, category, sp):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO backlog (sprint_id, ticket_id, title, assignee, role, category, sp) VALUES (?,?,?,?,?,?,?)",
        (int(sprint_id), ticket_id, title, assignee, role, category, float(sp))
    )
    conn.commit()
    conn.close()
    clear_db_caches()

def update_ticket(idx, ticket_id, title, assignee, category, sp, actual_sp, status, start_date, end_date):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """UPDATE backlog SET ticket_id=?, title=?, assignee=?, category=?, sp=?, actual_sp=?, status=?, start_date=?, end_date=? WHERE id=?""",
        (ticket_id, title, assignee, category, float(sp), float(actual_sp or 0), status, start_date, end_date, int(idx))
    )
    conn.commit()
    conn.close()
    clear_db_caches()

def delete_ticket(ticket_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM backlog WHERE ticket_id=?", (ticket_id,))
    conn.commit()
    conn.close()
    clear_db_caches()

def add_leave(name, reason, start_date, end_date, total_days, sprint_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO leaves (name, reason, start_date, end_date, total_days, sprint_id) VALUES (?,?,?,?,?,?)",
        (name, reason, str(start_date), str(end_date), int(total_days), int(sprint_id))
    )
    conn.commit()
    conn.close()
    clear_db_caches()

def update_leave(idx, name, reason, start_date, end_date, total_days):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE leaves SET name=?, reason=?, start_date=?, end_date=?, total_days=? WHERE id=?",
        (name, reason, str(start_date), str(end_date), int(total_days), int(idx))
    )
    conn.commit()
    conn.close()
    clear_db_caches()

def delete_leave(leave_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM leaves WHERE id=?", (int(leave_id),))
    conn.commit()
    conn.close()
    clear_db_caches()

def add_holiday(holiday_date, description, sprint_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO holidays (holiday_date, description, sprint_id) VALUES (?,?,?)",
        (str(holiday_date), description, int(sprint_id))
    )
    conn.commit()
    conn.close()
    clear_db_caches()

def update_holiday(idx, holiday_date, description):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE holidays SET holiday_date=?, description=? WHERE id=?",
        (str(holiday_date), description, int(idx))
    )
    conn.commit()
    conn.close()
    clear_db_caches()

def delete_holiday(holiday_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM holidays WHERE id=?", (int(holiday_id),))
    conn.commit()
    conn.close()
    clear_db_caches()

def add_team_member(name, role):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO team (name, role, daily_sp) VALUES (?,?,?)", (name, role, 2.0))
    conn.commit()
    conn.close()
    clear_db_caches()

def delete_team_member(member_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM team WHERE id=?", (int(member_id),))
    conn.commit()
    conn.close()
    clear_db_caches()

def launch_sprint(name, start_date, end_date):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE sprints SET status='Archived' WHERE status='Active'")
    c.execute("INSERT INTO sprints (name, start_date, end_date, status) VALUES (?,?,?, 'Active')", (name, str(start_date), str(end_date)))
    conn.commit()
    conn.close()
    clear_db_caches()

def update_sprint(idx, name, start_date, end_date, status):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE sprints SET name=?, start_date=?, end_date=?, status=? WHERE id=?",
        (name, str(start_date), str(end_date), status, int(idx))
    )
    conn.commit()
    conn.close()
    clear_db_caches()

def delete_sprint(sprint_name):
    conn = get_connection()
    c = conn.cursor()
    # Find ID first to cascade
    c.execute("SELECT id FROM sprints WHERE name=?", (sprint_name,))
    row = c.fetchone()
    if row:
        sid = int(row[0])
        c.execute("DELETE FROM backlog WHERE sprint_id=?", (sid,))
        c.execute("DELETE FROM leaves WHERE sprint_id=?", (sid,))
        c.execute("DELETE FROM holidays WHERE sprint_id=?", (sid,))
        c.execute("DELETE FROM sprints WHERE id=?", (sid,))
        conn.commit()
    conn.close()
    clear_db_caches()
