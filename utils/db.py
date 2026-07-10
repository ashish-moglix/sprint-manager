import os
import pymongo
import pandas as pd
import streamlit as st
from bson import ObjectId
from utils.hash import hash_password

# Load MongoDB connection URI from environment variable, with fallback
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://localhost:27017/sprint-cockpit"
)

class DuplicateUserError(Exception):
    """Custom exception raised when trying to add a member who already belongs to a team."""
    def __init__(self, team_name, admin_email):
        self.team_name = team_name
        self.admin_email = admin_email
        super().__init__(f"User is already part of team {team_name}. Connect with admin: {admin_email}")

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

def get_current_team_id():
    """Get the current user's team ID from session state."""
    if "user" in st.session_state and st.session_state.user:
        return st.session_state.user.get("team_id")
    return None

def init_db():
    """Initialize default team, Super Admin, and migrate legacy SQLite team members if necessary."""
    db = get_mongo_db()
    
    # 1. Create Default Team if none exist
    if db['teams'].count_documents({}) == 0:
        default_team = {"name": "Default Team"}
        res = db['teams'].insert_one(default_team)
        default_team_id = str(res.inserted_id)
    else:
        first_team = db['teams'].find_one()
        default_team_id = str(first_team['_id'])
        
    # 2. Create Super Admin if not exists
    if db['users'].count_documents({"user_role": "Super Admin"}) == 0:
        db['users'].insert_one({
            "email": "ashish.awasthi@moglix.com",
            "password": hash_password("EMAdmin@123"),
            "name": "Ashish Awasthi",
            "user_role": "Super Admin",
            "team_id": None
        })
        
    # 3. Migrate old team collection documents to users collection
    if db['team'].count_documents({}) > 0:
        for member in db['team'].find():
            email = f"{member['name'].replace(' ', '.').lower()}@moglix.com"
            if db['users'].count_documents({"email": email}) == 0:
                db['users'].insert_one({
                    "name": member['name'],
                    "email": email,
                    "password": hash_password("Welcome@123"),
                    "user_role": "Team User",
                    "team_id": default_team_id,
                    "role": member['role'],
                    "daily_sp": float(member.get('daily_sp', 2.0)),
                    "bug_p": float(member.get('bug_p', 15.0)),
                    "adhoc_p": float(member.get('adhoc_p', 10.0)),
                    "ceremony_p": float(member.get('ceremony_p', 10.0))
                })
        # Drop the old team collection so we don't migrate multiple times
        db['team'].drop()

    # 4. Fill in missing team_id in sprints, backlog, leaves, holidays
    for coll in ['sprints', 'backlog', 'leaves', 'holidays']:
        db[coll].update_many({"team_id": {"$exists": False}}, {"$set": {"team_id": default_team_id}})

# --- SUPER ADMIN DATABASE OPERATIONS ---

def get_teams():
    """Retrieve all teams."""
    db = get_mongo_db()
    cursor = db['teams'].find()
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    else:
        df = pd.DataFrame(columns=['id', 'name'])
    return df

def add_team(name):
    """Add a new team."""
    db = get_mongo_db()
    if db['teams'].count_documents({"name": name.strip()}) == 0:
        db['teams'].insert_one({"name": name.strip()})
        clear_db_caches()

def delete_team(team_id):
    """Delete a team and cascade delete all its related documents."""
    db = get_mongo_db()
    db['teams'].delete_one({"_id": ObjectId(team_id)})
    db['users'].delete_many({"team_id": str(team_id)})
    db['sprints'].delete_many({"team_id": str(team_id)})
    db['backlog'].delete_many({"team_id": str(team_id)})
    db['leaves'].delete_many({"team_id": str(team_id)})
    db['holidays'].delete_many({"team_id": str(team_id)})
    clear_db_caches()

def get_all_users():
    """Retrieve all users."""
    db = get_mongo_db()
    cursor = db['users'].find()
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    else:
        df = pd.DataFrame(columns=['id', 'name', 'email', 'password', 'user_role', 'team_id', 'role'])
    return df

# --- CACHED MULTI-TENANT READ OPERATIONS ---

def get_sprints():
    """Load all sprints for the active tenant team."""
    db = get_mongo_db()
    tid = get_current_team_id()
    cursor = db['sprints'].find({"team_id": str(tid)})
    df = pd.DataFrame(list(cursor))
    
    # Ensure expected columns always exist to prevent KeyErrors
    for col in ['id', 'name', 'start_date', 'end_date', 'status', 'actual_start_date', 'actual_end_date', 'team_id']:
        if col not in df.columns:
            df[col] = None

    if not df.empty:
        df['id'] = df['_id'].astype(str)
        df = df.sort_values(by='name', ascending=False)
    return df

def get_team():
    """Load the team roster (non-Super Admin users) for the active tenant team."""
    db = get_mongo_db()
    tid = get_current_team_id()
    cursor = db['users'].find({"team_id": str(tid), "user_role": {"$ne": "Super Admin"}})
    df = pd.DataFrame(list(cursor))
    if df.empty:
        df = pd.DataFrame(columns=['id', 'name', 'role', 'daily_sp', 'bug_p', 'adhoc_p', 'ceremony_p', 'email', 'user_role', 'team_id'])
    else:
        df['id'] = df['_id'].astype(str)
    return df

def get_leaves(sprint_id):
    """Load leaves related to a specific sprint for the active tenant team."""
    db = get_mongo_db()
    tid = get_current_team_id()
    cursor = db['leaves'].find({
        "team_id": str(tid),
        "$or": [{"sprint_id": str(sprint_id)}, {"sprint_id": 0}, {"sprint_id": "0"}]
    })
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    else:
        df = pd.DataFrame(columns=['id', 'name', 'reason', 'start_date', 'end_date', 'total_days', 'sprint_id', 'team_id'])
    return df

def get_leaves_with_sprints():
    """Load all leaves along with sprint name for the active tenant team."""
    tid = get_current_team_id()
    db = get_mongo_db()
    leaves_cursor = db['leaves'].find({"team_id": str(tid)})
    leaves_df = pd.DataFrame(list(leaves_cursor))
    if not leaves_df.empty:
        leaves_df['id'] = leaves_df['_id'].astype(str)
    
    sprints_cursor = db['sprints'].find({"team_id": str(tid)})
    sprints_df = pd.DataFrame(list(sprints_cursor))
    if not sprints_df.empty:
        sprints_df['id'] = sprints_df['_id'].astype(str)
    
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

def get_holidays(sprint_id, s_start, s_end):
    """Load holidays that fall within a sprint range for the active tenant team."""
    db = get_mongo_db()
    tid = get_current_team_id()
    cursor = db['holidays'].find({
        "team_id": str(tid),
        "sprint_id": str(sprint_id),
        "holiday_date": {"$gte": str(s_start), "$lte": str(s_end)}
    })
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    else:
        df = pd.DataFrame(columns=['id', 'holiday_date', 'description', 'sprint_id', 'team_id'])
    return df

def get_all_holidays():
    """Load all holidays along with sprint name for the active tenant team."""
    tid = get_current_team_id()
    db = get_mongo_db()
    hols_cursor = db['holidays'].find({"team_id": str(tid)})
    hols_df = pd.DataFrame(list(hols_cursor))
    if not hols_df.empty:
        hols_df['id'] = hols_df['_id'].astype(str)
        
    sprints_cursor = db['sprints'].find({"team_id": str(tid)})
    sprints_df = pd.DataFrame(list(sprints_cursor))
    if not sprints_df.empty:
        sprints_df['id'] = sprints_df['_id'].astype(str)
        
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

def get_backlog(sprint_id):
    """Load backlog tickets for a specific sprint for the active tenant team."""
    db = get_mongo_db()
    tid = get_current_team_id()
    cursor = db['backlog'].find({"team_id": str(tid), "sprint_id": str(sprint_id)})
    df = pd.DataFrame(list(cursor))
    if not df.empty:
        df['id'] = df['_id'].astype(str)
    else:
        df = pd.DataFrame(columns=['id', 'sprint_id', 'ticket_id', 'title', 'assignee', 'role', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date', 'team_id'])
    return df

# --- MUTATION OPERATIONS ---

def clear_db_caches():
    """Invalidate all cached read operations."""
    st.cache_data.clear()

def add_ticket(sprint_id, ticket_id, title, assignee, role, category, sp):
    db = get_mongo_db()
    tid = get_current_team_id()
    db['backlog'].insert_one({
        "team_id": str(tid),
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
    tid = get_current_team_id()
    db['leaves'].insert_one({
        "team_id": str(tid),
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
    tid = get_current_team_id()
    db['holidays'].insert_one({
        "team_id": str(tid),
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

def add_team_member(name, role, bug_p=15.0, adhoc_p=10.0, ceremony_p=10.0, email=None, password=None, user_role='Team User', team_id=None):
    db = get_mongo_db()
    target_team_id = team_id or get_current_team_id()
    
    # Generate default email if not provided
    if not email:
        email = f"{name.replace(' ', '.').lower()}@moglix.com"
    else:
        email = email.strip()
        
    # Ensure email or name is unique across all teams
    existing = db['users'].find_one({"$or": [{"email": email}, {"name": name}]})
    if existing:
        ex_team_id = existing.get("team_id")
        team_name = "Another Team"
        admin_email = "the admin"
        if ex_team_id:
            team_doc = db['teams'].find_one({"_id": ObjectId(ex_team_id)})
            if team_doc:
                team_name = team_doc['name']
            admin_doc = db['users'].find_one({"team_id": ex_team_id, "user_role": "Team Admin"})
            if admin_doc:
                admin_email = admin_doc['email']
        raise DuplicateUserError(team_name, admin_email)
        
    db['users'].insert_one({
        "name": name,
        "email": email,
        "password": hash_password(password or "Welcome@123"),
        "user_role": user_role,
        "team_id": str(target_team_id) if target_team_id else None,
        "role": role,
        "daily_sp": 2.0,
        "bug_p": float(bug_p),
        "adhoc_p": float(adhoc_p),
        "ceremony_p": float(ceremony_p)
    })
    clear_db_caches()

def update_team(team_id, new_name):
    """Update team name."""
    db = get_mongo_db()
    db['teams'].update_one(
        {"_id": ObjectId(team_id)},
        {"$set": {"name": new_name.strip()}}
    )
    clear_db_caches()

def update_team_member(idx, name, role, daily_sp, bug_p, adhoc_p, ceremony_p, email=None, password=None, user_role=None, team_id=None):
    db = get_mongo_db()
    update_fields = {
        "name": name,
        "role": role,
        "daily_sp": float(daily_sp),
        "bug_p": float(bug_p),
        "adhoc_p": float(adhoc_p),
        "ceremony_p": float(ceremony_p)
    }
    if email:
        update_fields["email"] = email
    if password:
        update_fields["password"] = password
    if user_role:
        update_fields["user_role"] = user_role
    if team_id:
        update_fields["team_id"] = str(team_id)
        
    db['users'].update_one(
        {"_id": ObjectId(idx)},
        {"$set": update_fields}
    )
    clear_db_caches()

def update_team_member_fields(idx, fields_dict):
    """Surgically update only modified fields of a team member in MongoDB."""
    db = get_mongo_db()
    if not fields_dict:
        return
    # Copy dictionary to prevent side-effects
    update_fields = dict(fields_dict)
    # Ensure numeric columns are floats
    for col in ["daily_sp", "bug_p", "adhoc_p", "ceremony_p"]:
        if col in update_fields:
            update_fields[col] = float(update_fields[col])
    db['users'].update_one(
        {"_id": ObjectId(idx)},
        {"$set": update_fields}
    )
    clear_db_caches()

def delete_team_member(member_id):
    db = get_mongo_db()
    db['users'].delete_one({"_id": ObjectId(member_id)})
    clear_db_caches()

def create_sprint(name, start_date, end_date):
    db = get_mongo_db()
    tid = get_current_team_id()
    db['sprints'].insert_one({
        "team_id": str(tid),
        "name": name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "status": "Draft",
        "actual_start_date": None,
        "actual_end_date": None
    })
    clear_db_caches()

def start_sprint(sprint_id, actual_start_date):
    db = get_mongo_db()
    tid = get_current_team_id()
    active_exists = db['sprints'].find_one({"team_id": str(tid), "status": "Active"})
    if active_exists:
        raise ValueError("Another sprint is currently active. Please stop it first.")
    db['sprints'].update_one(
        {"_id": ObjectId(sprint_id)},
        {"$set": {
            "status": "Active",
            "actual_start_date": str(actual_start_date)
        }}
    )
    clear_db_caches()

def stop_sprint(sprint_id, actual_end_date):
    db = get_mongo_db()
    db['sprints'].update_one(
        {"_id": ObjectId(sprint_id)},
        {"$set": {
            "status": "Archived",
            "actual_end_date": str(actual_end_date)
        }}
    )
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
    tid = get_current_team_id()
    spr = db['sprints'].find_one({"team_id": str(tid), "name": sprint_name})
    if spr:
        sid = str(spr['_id'])
        db['backlog'].delete_many({"team_id": str(tid), "sprint_id": sid})
        db['leaves'].delete_many({"team_id": str(tid), "sprint_id": sid})
        db['holidays'].delete_many({"team_id": str(tid), "sprint_id": sid})
        db['sprints'].delete_one({"_id": spr['_id']})
    clear_db_caches()

def save_sprint_report(report_doc):
    """Save or replace a sprint report."""
    db = get_mongo_db()
    db['reports'].replace_one(
        {"sprint_id": str(report_doc["sprint_id"])},
        report_doc,
        upsert=True
    )

def get_sprint_report(sprint_id):
    """Retrieve a sprint report by sprint ID."""
    db = get_mongo_db()
    return db['reports'].find_one({"sprint_id": str(sprint_id)})

def get_all_reports_for_team(team_id):
    """Retrieve all reports for a specific team, sorted by generation date."""
    db = get_mongo_db()
    cursor = db['reports'].find({"team_id": str(team_id)}).sort("generated_at", -1)
    return list(cursor)
