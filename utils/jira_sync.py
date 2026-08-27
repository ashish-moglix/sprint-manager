from utils.db import get_mongo_db, get_current_team_id, update_ticket_jira_comments
from utils.jira_client import (
    find_sprint_by_name, get_issues_by_sprint, parse_issue, parse_comment,
    get_comments, _base_url, DEFAULT_STORY_POINTS_FIELD
)


def get_team_jira_config():
    """Get JIRA config for the current team. Returns dict or None."""
    db = get_mongo_db()
    tid = get_current_team_id()
    team = db['teams'].find_one({"_id": __import__('bson').ObjectId(tid)})
    if not team or not team.get("jira_board_id"):
        return None
    return {
        "board_id": team["jira_board_id"],
        "base_url": team.get("jira_url", ""),
        "story_points_field": team.get("jira_story_points_field", DEFAULT_STORY_POINTS_FIELD),
    }


def _match_assignee_by_email(assignee_email):
    """Match JIRA assignee email to a sprint manager user. Returns user name or None."""
    if not assignee_email:
        return None
    db = get_mongo_db()
    tid = get_current_team_id()
    user = db['users'].find_one({
        "team_id": str(tid),
        "email": {"$regex": f"^{assignee_email}$", "$options": "i"}
    })
    return user["name"] if user else None


def _fetch_and_cache_comments(sprint_id, ticket_id, jira_key):
    """Fetch JIRA comments and cache them locally."""
    try:
        raw_comments = get_comments(jira_key)
        parsed = [parse_comment(c) for c in raw_comments]
        update_ticket_jira_comments(str(sprint_id), ticket_id, parsed)
    except Exception:
        pass


def sync_sprint_from_jira(sprint_id, sprint_name, board_id, base_url):
    """Sync tickets from JIRA into local backlog.

    Returns dict with counts: {"added": N, "skipped": N, "total_jira": N}
    """
    db = get_mongo_db()
    tid = get_current_team_id()

    jira_sprint = find_sprint_by_name(board_id, sprint_name)
    if not jira_sprint:
        return {"added": 0, "skipped": 0, "total_jira": 0,
                "error": f"Sprint '{sprint_name}' not found on JIRA board {board_id}"}

    jira_sprint_id = jira_sprint.get("id")
    sp_field = get_team_jira_config().get("story_points_field", DEFAULT_STORY_POINTS_FIELD)

    issues = get_issues_by_sprint(board_id, jira_sprint_id, story_points_field=sp_field)
    if not issues:
        return {"added": 0, "skipped": 0, "total_jira": 0}

    existing = db['backlog'].find({
        "team_id": str(tid),
        "sprint_id": str(sprint_id),
        "synced_from_jira": True
    })
    existing_keys = {t["jira_key"] for t in existing if t.get("jira_key")}

    added = 0
    skipped = 0

    for issue in issues:
        parsed = parse_issue(issue, base_url, story_points_field=sp_field)
        jira_key = parsed["jira_key"]

        if jira_key in existing_keys:
            skipped += 1
            _fetch_and_cache_comments(sprint_id, jira_key, jira_key)
            continue

        # Match assignee by email to sprint manager user
        matched_name = _match_assignee_by_email(parsed.get("assignee_email"))
        assignee = matched_name if matched_name else parsed["assignee"]

        db['backlog'].insert_one({
            "team_id": str(tid),
            "sprint_id": str(sprint_id),
            "ticket_id": jira_key,
            "title": parsed["title"],
            "assignee": assignee,
            "role": "",
            "category": parsed["category"],
            "sp": parsed["sp"],
            "actual_sp": 0.0,
            "status": "Todo",
            "start_date": None,
            "end_date": None,
            "jira_key": jira_key,
            "jira_url": parsed["jira_url"],
            "jira_status": parsed["jira_status"],
            "synced_from_jira": True,
            "jira_comments": [],
            "local_comments": [],
        })
        added += 1
        existing_keys.add(jira_key)

        _fetch_and_cache_comments(sprint_id, jira_key, jira_key)

    db['sprints'].update_one(
        {"_id": __import__('bson').ObjectId(sprint_id)},
        {"$set": {
            "jira_sync_enabled": True,
            "jira_sprint_id": jira_sprint_id,
            "last_jira_sync": __import__('datetime').datetime.utcnow().isoformat(),
        }}
    )

    return {"added": added, "skipped": skipped, "total_jira": len(issues)}
