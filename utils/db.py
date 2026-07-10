import os
import pymongo
import pandas as pd
import streamlit as st
from bson import ObjectId

# Load MongoDB connection URI from environment variable, with fallback
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://localhost:27017/sprint-cockpit"
)

def get_mongo_db():
    """Get MongoDB database connection."""
    client = pymongo.MongoClient(MONGO_URI)
    return client.get_default_database()

def get_collection_df(collection_name):
    """Retrieve collection content as a pandas DataFrame."""
    db = get_mongo_db()
    cursor = db[collection_name].find()
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    return df

def init_db():
    """Initialize default team members in MongoDB if empty."""
    db = get_mongo_db()
    if db['team'].count_documents({}) == 0:
        members = [
            {"name": 'Partha', "role": 'Backend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Kanchan', "role": 'Backend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Govind', "role": 'Backend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Biswajit', "role": 'Backend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Rohit', "role": 'Backend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Shashi', "role": 'Frontend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Junaid', "role": 'Frontend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Kabir', "role": 'Frontend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Meenakshi', "role": 'QA', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Kuldeep', "role": 'QA', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0},
            {"name": 'Ashish', "role": 'Backend', "daily_sp": 2.0, "bug_p": 15.0, "adhoc_p": 10.0, "ceremony_p": 10.0}
        ]
        db['team'].insert_many(members)

# --- CACHED READ OPERATIONS ---

@st.cache_data(ttl="15m")
def get_sprints():
    """Load all sprints from MongoDB."""
    df = get_collection_df('sprints')
    if not df.empty:
        df = df.sort_values(by='name', ascending=False)
    else:
        df = pd.DataFrame(columns=['id', 'name', 'start_date', 'end_date', 'status'])
    return df

@st.cache_data(ttl="15m")
def get_team():
    """Load the full team roster from MongoDB."""
    df = get_collection_df('team')
    if df.empty:
        df = pd.DataFrame(columns=['id', 'name', 'role', 'daily_sp', 'bug_p', 'adhoc_p', 'ceremony_p'])
    return df

@st.cache_data(ttl="15m")
def get_leaves(sprint_id):
    """Load leaves related to a specific sprint or global ones."""
    db = get_mongo_db()
    cursor = db['leaves'].find({"$or": [{"sprint_id": str(sprint_id)}, {"sprint_id": 0}, {"sprint_id": "0"}]})
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    else:
        df = pd.DataFrame(columns=['id', 'name', 'reason', 'start_date', 'end_date', 'total_days', 'sprint_id'])
    return df

@st.cache_data(ttl="15m")
def get_leaves_with_sprints():
    """Load all leaves along with sprint name."""
    leaves_df = get_collection_df('leaves')
    sprints_df = get_collection_df('sprints')
    if leaves_df.empty:
        return pd.DataFrame(columns=['id', 'name', 'sprint', 'reason', 'start_date', 'end_date', 'total_days'])
    if sprints_df.empty:
        leaves_df['sprint'] = "Unknown"
    else:
        sprints_df_renamed = sprints_df[['id', 'name']].rename(columns={'name': 'sprint_name', 'id': 'sprint_id'})
        leaves_df['sprint_id_str'] = leaves_df['sprint_id'].astype(str)
        sprints_df_renamed['sprint_id_str'] = sprints_df_renamed['sprint_id'].astype(str)
        merged = pd.merge(leaves_df, sprints_df_renamed, on='sprint_id_str', how='left')
        leaves_df['sprint'] = merged['sprint_name'].fillna('Global')
    return leaves_df[['id', 'name', 'sprint', 'reason', 'start_date', 'end_date', 'total_days']]

@st.cache_data(ttl="15m")
def get_holidays(sprint_id, s_start, s_end):
    """Load holidays that fall within a sprint range."""
    db = get_mongo_db()
    cursor = db['holidays'].find({
        "sprint_id": str(sprint_id),
        "holiday_date": {"$gte": str(s_start), "$lte": str(s_end)}
    })
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    else:
        df = pd.DataFrame(columns=['id', 'holiday_date', 'description', 'sprint_id'])
    return df

@st.cache_data(ttl="15m")
def get_all_holidays():
    """Load all holidays along with sprint name."""
    hols_df = get_collection_df('holidays')
    sprints_df = get_collection_df('sprints')
    if hols_df.empty:
        return pd.DataFrame(columns=['id', 'holiday_date', 'description', 'sprint'])
    if sprints_df.empty:
        hols_df['sprint'] = "Unknown"
    else:
        sprints_df_renamed = sprints_df[['id', 'name']].rename(columns={'name': 'sprint_name', 'id': 'sprint_id'})
        hols_df['sprint_id_str'] = hols_df['sprint_id'].astype(str)
        sprints_df_renamed['sprint_id_str'] = sprints_df_renamed['sprint_id'].astype(str)
        merged = pd.merge(hols_df, sprints_df_renamed, on='sprint_id_str', how='left')
        hols_df['sprint'] = merged['sprint_name'].fillna('Global')
    return hols_df[['id', 'holiday_date', 'description', 'sprint']]

@st.cache_data(ttl="15m")
def get_backlog(sprint_id):
    """Load backlog tickets for a specific sprint."""
    db = get_mongo_db()
    cursor = db['backlog'].find({"sprint_id": str(sprint_id)})
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    else:
        df = pd.DataFrame(columns=['id', 'sprint_id', 'ticket_id', 'title', 'assignee', 'role', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date'])
    return df

# --- MUTATION OPERATIONS (Mutate database and clear cache) ---

def clear_db_caches():
    """Invalidate all cached read operations."""
    st.cache_data.clear()

def add_ticket(sprint_id, ticket_id, title, assignee, role, category, sp):
    db = get_mongo_db()
    db['backlog'].insert_one({
        "sprint_id": str(sprint_id),
        "ticket_id": ticket_id,
        "title": title,
        "assignee": assignee,
        "role": role,
        "category": category,
        "sp": float(sp),
        "actual_sp": 0.0,
        "status": "Todo",
        "start_date": None,
        "end_date": None
    })
    clear_db_caches()

def update_ticket(idx, ticket_id, title, assignee, category, sp, actual_sp, status, start_date, end_date):
    db = get_mongo_db()
    db['backlog'].update_one(
        {"_id": ObjectId(idx)},
        {"$set": {
            "ticket_id": ticket_id,
            "title": title,
            "assignee": assignee,
            "category": category,
            "sp": float(sp),
            "actual_sp": float(actual_sp or 0.0),
            "status": status,
            "start_date": start_date,
            "end_date": end_date
        }}
    )
    clear_db_caches()

def delete_ticket(ticket_id):
    db = get_mongo_db()
    db['backlog'].delete_one({"ticket_id": ticket_id})
    clear_db_caches()

def add_leave(name, reason, start_date, end_date, total_days, sprint_id):
    db = get_mongo_db()
    db['leaves'].insert_one({
        "name": name,
        "reason": reason,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "total_days": int(total_days),
        "sprint_id": str(sprint_id)
    })
    clear_db_caches()

def update_leave(idx, name, reason, start_date, end_date, total_days):
    db = get_mongo_db()
    db['leaves'].update_one(
        {"_id": ObjectId(idx)},
        {"$set": {
            "name": name,
            "reason": reason,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_days": int(total_days)
        }}
    )
    clear_db_caches()

def delete_leave(leave_id):
    db = get_mongo_db()
    db['leaves'].delete_one({"_id": ObjectId(leave_id)})
    clear_db_caches()

def add_holiday(holiday_date, description, sprint_id):
    db = get_mongo_db()
    db['holidays'].insert_one({
        "holiday_date": str(holiday_date),
        "description": description,
        "sprint_id": str(sprint_id)
    })
    clear_db_caches()

def update_holiday(idx, holiday_date, description):
    db = get_mongo_db()
    db['holidays'].update_one(
        {"_id": ObjectId(idx)},
        {"$set": {
            "holiday_date": str(holiday_date),
            "description": description
        }}
    )
    clear_db_caches()

def delete_holiday(holiday_id):
    db = get_mongo_db()
    db['holidays'].delete_one({"_id": ObjectId(holiday_id)})
    clear_db_caches()

def add_team_member(name, role, bug_p=15.0, adhoc_p=10.0, ceremony_p=10.0):
    db = get_mongo_db()
    db['team'].insert_one({
        "name": name,
        "role": role,
        "daily_sp": 2.0,
        "bug_p": float(bug_p),
        "adhoc_p": float(adhoc_p),
        "ceremony_p": float(ceremony_p)
    })
    clear_db_caches()

def update_team_member(idx, name, role, daily_sp, bug_p, adhoc_p, ceremony_p):
    db = get_mongo_db()
    db['team'].update_one(
        {"_id": ObjectId(idx)},
        {"$set": {
            "name": name,
            "role": role,
            "daily_sp": float(daily_sp),
            "bug_p": float(bug_p),
            "adhoc_p": float(adhoc_p),
            "ceremony_p": float(ceremony_p)
        }}
    )
    clear_db_caches()

def delete_team_member(member_id):
    db = get_mongo_db()
    db['team'].delete_one({"_id": ObjectId(member_id)})
    clear_db_caches()

def launch_sprint(name, start_date, end_date):
    db = get_mongo_db()
    db['sprints'].update_many({"status": "Active"}, {"$set": {"status": "Archived"}})
    db['sprints'].insert_one({
        "name": name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "status": "Active"
    })
    clear_db_caches()

def update_sprint(idx, name, start_date, end_date, status):
    db = get_mongo_db()
    db['sprints'].update_one(
        {"_id": ObjectId(idx)},
        {"$set": {
            "name": name,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "status": status
        }}
    )
    clear_db_caches()

def delete_sprint(sprint_name):
    db = get_mongo_db()
    spr = db['sprints'].find_one({"name": sprint_name})
    if spr:
        sid = str(spr['_id'])
        db['backlog'].delete_many({"sprint_id": sid})
        db['leaves'].delete_many({"sprint_id": sid})
        db['holidays'].delete_many({"sprint_id": sid})
        db['sprints'].delete_one({"_id": spr['_id']})
    clear_db_caches()
