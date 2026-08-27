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

    # 5. Backfill actual_sp for existing tickets that have start/end dates but actual_sp is 0 or None
    from utils.helpers import get_workdays
    for ticket in db['backlog'].find({
        "start_date": {"$ne": None},
        "end_date": {"$ne": None},
        "$or": [{"actual_sp": 0.0}, {"actual_sp": None}]
    }):
        try:
            start = pd.to_datetime(ticket["start_date"]).date()
            end = pd.to_datetime(ticket["end_date"]).date()
            if pd.notna(start) and pd.notna(end):
                days = get_workdays(start, end)
                act_sp = round(days * 2, 2)
                db['backlog'].update_one(
                    {"_id": ticket["_id"]},
                    {"$set": {"actual_sp": float(act_sp)}}
                )
        except Exception:
            pass

    # 6. Backfill new role-specific fields for existing tickets
    new_fields = {
        'backend_assignee': None, 'frontend_assignee': None, 'qa_assignee': None,
        'backend_sp': 0.0, 'frontend_sp': 0.0, 'qa_sp': 0.0,
        'backend_start_date': None, 'backend_end_date': None,
        'frontend_start_date': None, 'frontend_end_date': None,
        'qa_start_date': None, 'qa_end_date': None,
        'backend_status': 'Todo', 'frontend_status': 'Todo', 'qa_status': 'Todo',
    }
    try:
        for field in new_fields:
            db['backlog'].update_many(
                {field: {"$exists": False}},
                {"$set": {field: new_fields[field]}}
            )
            clear_db_caches()
    except Exception:
        pass

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
        df = pd.DataFrame(columns=['id', 'name', 'role', 'daily_sp', 'bug_p', 'adhoc_p', 'ceremony_p', 'email', 'user_role', 'team_id', 'jira_account_id'])
    else:
        df['id'] = df['_id'].astype(str)
        if 'jira_account_id' not in df.columns:
            df['jira_account_id'] = None
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
    expected_cols = ['id', 'sprint_id', 'ticket_id', 'title', 'assignee', 'role', 'category', 'sp', 'actual_sp', 'status', 'start_date', 'end_date', 'team_id',
                    'jira_key', 'jira_url', 'jira_status', 'jira_push_status', 'synced_from_jira', 'jira_comments', 'local_comments',
                    'backend_assignee', 'frontend_assignee', 'qa_assignee',
                    'backend_sp', 'frontend_sp', 'qa_sp',
                    'backend_start_date', 'backend_end_date',
                    'frontend_start_date', 'frontend_end_date',
                    'qa_start_date', 'qa_end_date',
                    'backend_status', 'frontend_status', 'qa_status']
    if not df.empty:
        df['id'] = df['_id'].astype(str)
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None
    else:
        df = pd.DataFrame(columns=expected_cols)
    return df

# --- MUTATION OPERATIONS ---

def clear_db_caches():
    """Invalidate all cached read operations."""
    st.cache_data.clear()

def add_ticket(sprint_id, ticket_id, title, assignee, role, category, sp,
               backend_assignee=None, frontend_assignee=None, qa_assignee=None,
               backend_sp=None, frontend_sp=None, qa_sp=None,
               backend_start_date=None, backend_end_date=None,
               frontend_start_date=None, frontend_end_date=None,
               qa_start_date=None, qa_end_date=None,
               backend_status=None, frontend_status=None, qa_status=None):
    db = get_mongo_db()
    tid = get_current_team_id()
    doc = {
        "team_id": str(tid),
        "sprint_id": str(sprint_id),
        "ticket_id": ticket_id,
        "title": title,
        "assignee": assignee,
        "role": role,
        "category": category,
        "sp": float(sp or 0.0),
        "actual_sp": 0.0,
        "status": "Todo",
        "start_date": None,
        "end_date": None
    }
    # Add role-specific fields if provided
    if backend_assignee is not None:
        doc["backend_assignee"] = backend_assignee
    if frontend_assignee is not None:
        doc["frontend_assignee"] = frontend_assignee
    if qa_assignee is not None:
        doc["qa_assignee"] = qa_assignee
    if backend_sp is not None:
        doc["backend_sp"] = float(backend_sp)
    if frontend_sp is not None:
        doc["frontend_sp"] = float(frontend_sp)
    if qa_sp is not None:
        doc["qa_sp"] = float(qa_sp)
    if backend_start_date is not None:
        doc["backend_start_date"] = backend_start_date
    if backend_end_date is not None:
        doc["backend_end_date"] = backend_end_date
    if frontend_start_date is not None:
        doc["frontend_start_date"] = frontend_start_date
    if frontend_end_date is not None:
        doc["frontend_end_date"] = frontend_end_date
    if qa_start_date is not None:
        doc["qa_start_date"] = qa_start_date
    if qa_end_date is not None:
        doc["qa_end_date"] = qa_end_date
    if backend_status is not None:
        doc["backend_status"] = backend_status
    if frontend_status is not None:
        doc["frontend_status"] = frontend_status
    if qa_status is not None:
        doc["qa_status"] = qa_status

    db['backlog'].insert_one(doc)
    clear_db_caches()

def update_ticket(idx, ticket_id, title, assignee, category, sp, actual_sp, status, start_date, end_date,
                  backend_assignee=None, frontend_assignee=None, qa_assignee=None,
                  backend_sp=None, frontend_sp=None, qa_sp=None,
                  backend_start_date=None, backend_end_date=None,
                  frontend_start_date=None, frontend_end_date=None,
                  qa_start_date=None, qa_end_date=None,
                  backend_status=None, frontend_status=None, qa_status=None):
    db = get_mongo_db()
    updates = {
        "ticket_id": ticket_id,
        "title": title,
        "assignee": assignee,
        "category": category,
        "sp": float(sp),
        "actual_sp": float(actual_sp or 0.0),
        "status": status,
        "start_date": start_date,
        "end_date": end_date
    }
    # Add role-specific fields if provided
    if backend_assignee is not None:
        updates["backend_assignee"] = backend_assignee
    if frontend_assignee is not None:
        updates["frontend_assignee"] = frontend_assignee
    if qa_assignee is not None:
        updates["qa_assignee"] = qa_assignee
    if backend_sp is not None:
        updates["backend_sp"] = float(backend_sp)
    if frontend_sp is not None:
        updates["frontend_sp"] = float(frontend_sp)
    if qa_sp is not None:
        updates["qa_sp"] = float(qa_sp)
    if backend_start_date is not None:
        updates["backend_start_date"] = backend_start_date
    if backend_end_date is not None:
        updates["backend_end_date"] = backend_end_date
    if frontend_start_date is not None:
        updates["frontend_start_date"] = frontend_start_date
    if frontend_end_date is not None:
        updates["frontend_end_date"] = frontend_end_date
    if qa_start_date is not None:
        updates["qa_start_date"] = qa_start_date
    if qa_end_date is not None:
        updates["qa_end_date"] = qa_end_date
    if backend_status is not None:
        updates["backend_status"] = backend_status
    if frontend_status is not None:
        updates["frontend_status"] = frontend_status
    if qa_status is not None:
        updates["qa_status"] = qa_status

    db['backlog'].update_one({"_id": ObjectId(idx)}, {"$set": updates})
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
        
    # Ensure email is unique across all teams
    existing = db['users'].find_one({"email": email})
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

# --- JIRA INTEGRATION ---

def update_team_jira_config(team_id, jira_board_id, jira_url, jira_story_points_field=None):
    """Store JIRA board ID, base URL, and story points field on the team document."""
    db = get_mongo_db()
    fields = {
        "jira_board_id": jira_board_id,
        "jira_url": jira_url.rstrip("/") if jira_url else None
    }
    if jira_story_points_field:
        fields["jira_story_points_field"] = jira_story_points_field
    db['teams'].update_one(
        {"_id": ObjectId(team_id)},
        {"$set": fields}
    )
    clear_db_caches()

def get_team_jira_config(team_id):
    """Get JIRA config for a team. Returns dict with board_id, url, story_points_field or None."""
    db = get_mongo_db()
    team = db['teams'].find_one({"_id": ObjectId(team_id)})
    if not team or not team.get("jira_board_id"):
        return None
    return {
        "board_id": team["jira_board_id"],
        "url": team.get("jira_url", ""),
        "story_points_field": team.get("jira_story_points_field", "customfield_10119")
    }

def get_current_team_jira_config():
    """Convenience: JIRA config for the current session's team."""
    tid = get_current_team_id()
    if not tid:
        return None
    return get_team_jira_config(tid)


# --- JIRA CREDENTIAL STORAGE (ENCRYPTED) ---

def save_jira_credentials(token, email, base_url, story_points_field=None, start_date_field=None, end_date_field=None, actual_sp_field=None):
    """Encrypt and store JIRA connection credentials in the jira_config collection."""
    from utils.encryption import encrypt_value
    db = get_mongo_db()
    doc = {
        "_id": "global_jira_config",
        "encrypted_token": encrypt_value(token),
        "encrypted_email": encrypt_value(email),
        "encrypted_base_url": encrypt_value(base_url.rstrip("/") if base_url else ""),
        "encrypted_sp_field": encrypt_value(story_points_field) if story_points_field else None,
        "encrypted_start_date_field": encrypt_value(start_date_field) if start_date_field else None,
        "encrypted_end_date_field": encrypt_value(end_date_field) if end_date_field else None,
        "encrypted_actual_sp_field": encrypt_value(actual_sp_field) if actual_sp_field else None,
        "updated_at": __import__('datetime').datetime.utcnow().isoformat(),
    }
    db['jira_config'].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    clear_db_caches()


def get_jira_credentials():
    """Retrieve and decrypt JIRA credentials. Returns dict or None."""
    from utils.encryption import decrypt_value
    db = get_mongo_db()
    doc = db['jira_config'].find_one({"_id": "global_jira_config"})
    if not doc:
        return None
    try:
        return {
            "token": decrypt_value(doc["encrypted_token"]),
            "email": decrypt_value(doc["encrypted_email"]),
            "base_url": decrypt_value(doc["encrypted_base_url"]),
            "story_points_field": decrypt_value(doc["encrypted_sp_field"]) if doc.get("encrypted_sp_field") else None,
            "start_date_field": decrypt_value(doc["encrypted_start_date_field"]) if doc.get("encrypted_start_date_field") else None,
            "end_date_field": decrypt_value(doc["encrypted_end_date_field"]) if doc.get("encrypted_end_date_field") else None,
            "actual_sp_field": decrypt_value(doc["encrypted_actual_sp_field"]) if doc.get("encrypted_actual_sp_field") else None,
        }
    except Exception:
        return None


def clear_jira_credentials():
    """Remove stored JIRA credentials."""
    db = get_mongo_db()
    db['jira_config'].delete_one({"_id": "global_jira_config"})
    clear_db_caches()


def migrate_credentials_from_secrets():
    """One-time migration: Load credentials from secrets.toml if DB has test/placeholder values."""
    import os
    import streamlit as st

    db = get_mongo_db()
    doc = db['jira_config'].find_one({"_id": "global_jira_config"})

    if not doc:
        return False

    # Check if credentials look like test values
    from utils.encryption import decrypt_value
    try:
        token = decrypt_value(doc["encrypted_token"])
        email = decrypt_value(doc["encrypted_email"])

        print(f"DEBUG: Token starts with 'test_': {token.startswith('test_')}")
        print(f"DEBUG: Email is test@example.com: {email == 'test@example.com'}")

        # If token starts with "test_" or email is test@example.com, migrate from secrets
        if token.startswith("test_") or email == "test@example.com":
            secrets_token = st.secrets.get("JIRA_ACCESS_TOKEN", "")
            secrets_email = st.secrets.get("JIRA_EMAIL", "")
            secrets_url = st.secrets.get("JIRA_BASE_URL", "")

            print(f"DEBUG: Secrets token exists: {bool(secrets_token)}")
            print(f"DEBUG: Secrets email: {secrets_email}")

            if secrets_token and secrets_email:
                from utils.encryption import encrypt_value
                db['jira_config'].update_one(
                    {"_id": "global_jira_config"},
                    {"$set": {
                        "encrypted_token": encrypt_value(secrets_token),
                        "encrypted_email": encrypt_value(secrets_email),
                        "encrypted_base_url": encrypt_value(secrets_url.rstrip("/")) if secrets_url else None,
                        "updated_at": __import__('datetime').datetime.utcnow().isoformat()
                    }}
                )
                clear_db_caches()
                print("DEBUG: Migration successful!")
                return True
            else:
                print("DEBUG: Secrets not found")
    except Exception as e:
        print(f"DEBUG: Migration error: {e}")

    return False

def update_sprint_jira_fields(sprint_id, jira_sprint_id=None, last_sync=None, enabled=None):
    """Update JIRA sync metadata on a sprint."""
    db = get_mongo_db()
    fields = {}
    if jira_sprint_id is not None:
        fields["jira_sprint_id"] = jira_sprint_id
    if last_sync is not None:
        fields["last_jira_sync"] = last_sync
    if enabled is not None:
        fields["jira_sync_enabled"] = enabled
    if fields:
        db['sprints'].update_one(
            {"_id": ObjectId(sprint_id)},
            {"$set": fields}
        )
        clear_db_caches()

def get_tickets_by_jira_keys(sprint_id, jira_keys):
    """Find existing tickets in a sprint by their JIRA keys. Returns set of jira_key strings."""
    db = get_mongo_db()
    tid = get_current_team_id()
    cursor = db['backlog'].find({
        "team_id": str(tid),
        "sprint_id": str(sprint_id),
        "jira_key": {"$in": list(jira_keys)}
    })
    return {t["jira_key"] for t in cursor if t.get("jira_key")}


# --- JIRA USER LINKING ---

def get_user_jira_account_id(user_name):
    """Get JIRA accountId for a team member by name. Returns str or None."""
    db = get_mongo_db()
    tid = get_current_team_id()
    user = db['users'].find_one({"team_id": str(tid), "name": user_name})
    if user:
        return user.get("jira_account_id")
    return None

def update_user_jira_account_id(user_id, jira_account_id):
    """Store JIRA accountId on a user document for assignee matching."""
    db = get_mongo_db()
    db['users'].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"jira_account_id": jira_account_id.strip() if jira_account_id else None}}
    )
    clear_db_caches()


# --- JIRA PUSH TRACKING ---

def update_ticket_jira_push_status(sprint_id, ticket_id, status, timestamp):
    """Update the JIRA push status of a ticket."""
    db = get_mongo_db()
    tid = get_current_team_id()
    db['backlog'].update_one(
        {"team_id": str(tid), "sprint_id": str(sprint_id), "ticket_id": ticket_id},
        {"$set": {"jira_push_status": status, "last_jira_push": timestamp}}
    )
    clear_db_caches()


# --- COMMENTS ---

def add_ticket_comment(sprint_id, ticket_id, author, email, body):
    """Add a local comment to a ticket."""
    db = get_mongo_db()
    tid = get_current_team_id()
    from datetime import datetime, timezone
    comment = {
        "author": author,
        "email": email,
        "body": body,
        "created": datetime.now(timezone.utc).isoformat(),
        "source": "local",
        "synced": False,
    }
    db['backlog'].update_one(
        {"team_id": str(tid), "sprint_id": str(sprint_id), "ticket_id": ticket_id},
        {"$push": {"local_comments": comment}}
    )
    clear_db_caches()

def get_ticket_comments(sprint_id, ticket_id):
    """Get all comments for a ticket (local + cached JIRA). Returns list of comment dicts."""
    db = get_mongo_db()
    tid = get_current_team_id()
    ticket = db['backlog'].find_one({
        "team_id": str(tid),
        "sprint_id": str(sprint_id),
        "ticket_id": ticket_id
    })
    if not ticket:
        return []
    comments = []
    for c in ticket.get("jira_comments", []):
        comments.append(c)
    for c in ticket.get("local_comments", []):
        comments.append(c)
    comments.sort(key=lambda x: x.get("created", ""))
    return comments

def update_ticket_jira_comments(sprint_id, ticket_id, comments):
    """Cache JIRA comments locally on the ticket."""
    db = get_mongo_db()
    tid = get_current_team_id()
    db['backlog'].update_one(
        {"team_id": str(tid), "sprint_id": str(sprint_id), "ticket_id": ticket_id},
        {"$set": {"jira_comments": comments}}
    )
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
