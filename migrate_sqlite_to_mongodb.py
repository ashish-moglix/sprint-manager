import sqlite3
import os
import pymongo
import pandas as pd
from bson import ObjectId

SQLITE_DB = 'em_v10_final.db'
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://dev:credlix%40123@10.10.202.31:27018/sprint-cockpit?authSource=credlix-exim"
)

def migrate():
    if not os.path.exists(SQLITE_DB):
        print(f"Error: SQLite database file '{SQLITE_DB}' not found.")
        return

    print("Connecting to SQLite...")
    sqlite_conn = sqlite3.connect(SQLITE_DB)

    print("Connecting to MongoDB...")
    mongo_client = pymongo.MongoClient(MONGO_URI)
    db = mongo_client.get_default_database()

    print("Clearing existing MongoDB collections to prevent duplicates...")
    db['team'].delete_many({})
    db['sprints'].delete_many({})
    db['backlog'].delete_many({})
    db['leaves'].delete_many({})
    db['holidays'].delete_many({})

    # 1. Migrate Team
    print("Migrating Team...")
    team_df = pd.read_sql("SELECT * FROM team", sqlite_conn)
    if not team_df.empty:
        team_docs = []
        for _, row in team_df.iterrows():
            team_docs.append({
                "name": row['name'],
                "role": row['role'],
                "daily_sp": float(row.get('daily_sp', 2.0)),
                "bug_p": float(row.get('bug_p', 15.0)),
                "adhoc_p": float(row.get('adhoc_p', 10.0)),
                "ceremony_p": float(row.get('ceremony_p', 10.0))
            })
        db['team'].insert_many(team_docs)
        print(f"Migrated {len(team_docs)} team members.")

    # 2. Migrate Sprints and build ID map
    print("Migrating Sprints...")
    sprints_df = pd.read_sql("SELECT * FROM sprints", sqlite_conn)
    sprint_id_map = {} # sqlite_id -> mongo_id_str
    if not sprints_df.empty:
        for _, row in sprints_df.iterrows():
            res = db['sprints'].insert_one({
                "name": row['name'],
                "start_date": str(row['start_date']),
                "end_date": str(row['end_date']),
                "status": row['status']
            })
            sprint_id_map[int(row['id'])] = str(res.inserted_id)
        print(f"Migrated {len(sprints_df)} sprints.")

    # 3. Migrate Backlog
    print("Migrating Backlog...")
    backlog_df = pd.read_sql("SELECT * FROM backlog", sqlite_conn)
    if not backlog_df.empty:
        backlog_docs = []
        for _, row in backlog_df.iterrows():
            old_sid = row['sprint_id']
            # Map old integer ID to new string ObjectId or keep fallback
            new_sid = sprint_id_map.get(int(old_sid)) if pd.notna(old_sid) else None
            
            backlog_docs.append({
                "sprint_id": str(new_sid) if new_sid else None,
                "ticket_id": row['ticket_id'],
                "title": row['title'],
                "assignee": row['assignee'],
                "role": row['role'],
                "category": row['category'],
                "sp": float(row['sp']) if pd.notna(row['sp']) else 0.0,
                "actual_sp": float(row.get('actual_sp', 0.0)) if pd.notna(row.get('actual_sp')) else 0.0,
                "status": row.get('status', 'Todo'),
                "start_date": str(row['start_date']) if pd.notna(row['start_date']) else None,
                "end_date": str(row['end_date']) if pd.notna(row['end_date']) else None
            })
        if backlog_docs:
            db['backlog'].insert_many(backlog_docs)
            print(f"Migrated {len(backlog_docs)} backlog tickets.")

    # 4. Migrate Leaves
    print("Migrating Leaves...")
    leaves_df = pd.read_sql("SELECT * FROM leaves", sqlite_conn)
    if not leaves_df.empty:
        leaves_docs = []
        for _, row in leaves_df.iterrows():
            old_sid = row.get('sprint_id', 0)
            new_sid = sprint_id_map.get(int(old_sid)) if pd.notna(old_sid) and int(old_sid) in sprint_id_map else "0"
            
            leaves_docs.append({
                "name": row['name'],
                "reason": row['reason'],
                "start_date": str(row['start_date']),
                "end_date": str(row['end_date']),
                "total_days": int(row['total_days']),
                "sprint_id": str(new_sid)
            })
        if leaves_docs:
            db['leaves'].insert_many(leaves_docs)
            print(f"Migrated {len(leaves_docs)} leave entries.")

    # 5. Migrate Holidays
    print("Migrating Holidays...")
    holidays_df = pd.read_sql("SELECT * FROM holidays", sqlite_conn)
    if not holidays_df.empty:
        holidays_docs = []
        for _, row in holidays_df.iterrows():
            old_sid = row.get('sprint_id', 0)
            new_sid = sprint_id_map.get(int(old_sid)) if pd.notna(old_sid) and int(old_sid) in sprint_id_map else "0"
            
            holidays_docs.append({
                "holiday_date": str(row['holiday_date']),
                "description": row['description'],
                "sprint_id": str(new_sid)
            })
        if holidays_docs:
            db['holidays'].insert_many(holidays_docs)
            print(f"Migrated {len(holidays_docs)} holiday entries.")

    sqlite_conn.close()
    print("Migration successfully completed!")

if __name__ == "__main__":
    migrate()
