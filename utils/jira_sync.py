from utils.db import (
    get_mongo_db, get_current_team_id, update_ticket_jira_comments,
    get_team, assign_round_robin, get_jira_status_mapping, get_team_jira_sync_settings
)
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
    """Fetch JIRA comments and cache them locally, skipping ones that were pushed from here."""
    try:
        raw_comments = get_comments(jira_key)
        parsed = [parse_comment(c) for c in raw_comments]

        db = get_mongo_db()
        tid = get_current_team_id()
        ticket = db['backlog'].find_one({
            "team_id": str(tid),
            "sprint_id": str(sprint_id),
            "ticket_id": ticket_id
        })
        synced_local_bodies = set()
        if ticket:
            for c in ticket.get("local_comments", []):
                if c.get("synced"):
                    synced_local_bodies.add(c.get("body", "").strip())

        filtered = []
        for c in parsed:
            body = c.get("body", "")
            if "— (via Agile Portal)" in body:
                local_part = body.split("— (via Agile Portal)")[0].strip()
                if local_part in synced_local_bodies:
                    continue
            filtered.append(c)

        update_ticket_jira_comments(str(sprint_id), ticket_id, filtered)
    except Exception:
        pass


def _split_sp_for_roles(total_sp, has_be, has_fe, has_qa):
    """Split total SP across roles that have assignees.

    Distributes evenly; remainder goes to the first active role.
    Each role gets at least 0.5 SP if it has an assignee and total > 0.
    """
    active = [r for r, active in [("be", has_be), ("fe", has_fe), ("qa", has_qa)] if active]
    if not active or total_sp <= 0:
        return (total_sp if has_be else 0.0, total_sp if has_fe else 0.0, total_sp if has_qa else 0.0)

    per_role = round(total_sp / len(active), 1)
    remainder = round(total_sp - per_role * len(active), 1)

    be_sp = per_role + remainder if "be" in active else 0.0
    fe_sp = per_role if "fe" in active else 0.0
    qa_sp = per_role if "qa" in active else 0.0

    # Ensure each active role gets at least 0.5
    if has_be and be_sp < 0.5 and total_sp >= 0.5:
        be_sp = 0.5
    if has_fe and fe_sp < 0.5 and total_sp >= 0.5:
        fe_sp = 0.5
    if has_qa and qa_sp < 0.5 and total_sp >= 0.5:
        qa_sp = 0.5

    return (be_sp, fe_sp, qa_sp)


def _derive_portal_status(jira_status):
    """Map JIRA status to initial portal status.

    Recognizes common JIRA statuses; defaults to 'Todo' for unknown.
    """
    if not jira_status:
        return "Todo"
    status_map = {
        "to do": "Todo",
        "todo": "Todo",
        "backlog": "Todo",
        "open": "Todo",
        "reopened": "Todo",
        "in progress": "In Progress",
        "in review": "In Progress",
        "in development": "In Progress",
        "in testing": "In Progress",
        "qa": "In Progress",
        "done": "Done",
        "closed": "Done",
        "resolved": "Done",
        "verified": "Done",
    }
    return status_map.get(jira_status.strip().lower(), "Todo")


def sync_sprint_from_jira(sprint_id, sprint_name, board_id, base_url):
    """Sync tickets from JIRA into local backlog.

    Tickets with closed/Done/Resolved JIRA status are skipped based on team config.
    Initial portal status is derived from JIRA status.

    Returns dict with counts: {"added": N, "skipped": N, "skipped_closed": N, "total_jira": N}
    """
    db = get_mongo_db()
    tid = get_current_team_id()
    team_df = get_team()

    jira_sprint = find_sprint_by_name(board_id, sprint_name)
    if not jira_sprint:
        return {"added": 0, "skipped": 0, "skipped_closed": 0, "total_jira": 0,
                "error": f"Sprint '{sprint_name}' not found on JIRA board {board_id}"}

    jira_sprint_id = jira_sprint.get("id")
    sp_field = get_team_jira_config().get("story_points_field", DEFAULT_STORY_POINTS_FIELD)

    # Get team's skip config
    team = db['teams'].find_one({"_id": __import__('bson').ObjectId(tid)})
    skip_closed = team.get("jira_skip_closed_on_sync", True) if team else True
    mapping_doc = get_jira_status_mapping(str(tid))
    skip_statuses = set()
    if mapping_doc and mapping_doc.get("skip_statuses"):
        skip_statuses = {s.strip().lower() for s in mapping_doc["skip_statuses"] if s.strip()}
    elif skip_closed:
        skip_statuses = {"done", "closed", "resolved"}

    issues = get_issues_by_sprint(board_id, jira_sprint_id, story_points_field=sp_field)
    if not issues:
        return {"added": 0, "skipped": 0, "skipped_closed": 0, "total_jira": 0}

    existing = db['backlog'].find({
        "team_id": str(tid),
        "sprint_id": str(sprint_id),
        "synced_from_jira": True
    })
    existing_keys = {t["jira_key"] for t in existing if t.get("jira_key")}
    print(f"[SYNC DEBUG] team_id={tid}, sprint_id={sprint_id}, existing_keys count={len(existing_keys)}")

    added = 0
    skipped = 0
    skipped_closed = 0
    errors = []

    for issue in issues:
        try:
            parsed = parse_issue(issue, base_url, story_points_field=sp_field)
            jira_key = parsed["jira_key"]
            jira_status = parsed.get("jira_status", "")

            # Skip already-closed JIRA tickets
            if jira_status.strip().lower() in skip_statuses:
                skipped_closed += 1
                print(f"[SYNC] Skipping closed ticket {jira_key} (JIRA status: {jira_status})")
                continue

            if jira_key in existing_keys:
                skipped += 1
                _fetch_and_cache_comments(sprint_id, jira_key, jira_key)
                new_desc = parsed.get("description", "")
                result = db['backlog'].update_one(
                    {"team_id": str(tid), "sprint_id": str(sprint_id), "jira_key": jira_key},
                    {"$set": {
                        "title": parsed["title"],
                        "description": new_desc,
                        "jira_status": parsed["jira_status"],
                        "sp": parsed["sp"],
                        "issue_type": parsed.get("issue_type", ""),
                    }}
                )
                existing_doc = db['backlog'].find_one(
                    {"team_id": str(tid), "sprint_id": str(sprint_id), "jira_key": jira_key},
                    {"description": 1}
                )
                print(f"[SYNC DEBUG] Updated {jira_key}: matched={result.matched_count}, modified={result.modified_count}, desc_len={len(new_desc)}, stored_desc={existing_doc.get('description')!r}")
                continue

            # Match assignee by email to sprint manager user
            matched_name = _match_assignee_by_email(parsed.get("assignee_email"))
            assignee = matched_name if matched_name else parsed["assignee"]

            issue_type = parsed.get("issue_type", "")
            parent_key = parsed.get("parent_key", "")
            is_epic = issue_type.lower() == "epic"

            if is_epic:
                backend_assignee = frontend_assignee = qa_assignee = None
            else:
                backend_assignee = assign_round_robin("backend", team_df, sprint_id)
                frontend_assignee = assign_round_robin("frontend", team_df, sprint_id)
                qa_assignee = assign_round_robin("qa", team_df, sprint_id)

            initial_status = _derive_portal_status(jira_status)
            total_sp = parsed["sp"]
            be_sp, fe_sp, qa_sp = _split_sp_for_roles(
                total_sp, bool(backend_assignee), bool(frontend_assignee), bool(qa_assignee)
            )

            db['backlog'].insert_one({
                "team_id": str(tid),
                "sprint_id": str(sprint_id),
                "ticket_id": jira_key,
                "title": parsed["title"],
                "description": parsed.get("description", ""),
                "assignee": assignee,
                "role": "",
                "category": parsed["category"],
                "issue_type": issue_type,
                "sp": total_sp,
                "actual_sp": 0.0,
                "status": initial_status,
                "start_date": None,
                "end_date": None,
                "jira_key": jira_key,
                "jira_url": parsed["jira_url"],
                "jira_status": jira_status,
                "synced_from_jira": True,
                "jira_comments": [],
                "local_comments": [],
                "backend_assignee": backend_assignee,
                "frontend_assignee": frontend_assignee,
                "qa_assignee": qa_assignee,
                "backend_sp": be_sp,
                "frontend_sp": fe_sp,
                "qa_sp": qa_sp,
                "backend_status": initial_status if backend_assignee else "NA",
                "frontend_status": initial_status if frontend_assignee else "NA",
                "qa_status": initial_status if qa_assignee else "NA",
                "jira_parent_key": parent_key,
                "jira_status_push_history": [],
            })
            added += 1
            existing_keys.add(jira_key)

            _fetch_and_cache_comments(sprint_id, jira_key, jira_key)

        except Exception as e:
            jira_key = issue.get("key", "unknown")
            errors.append(f"{jira_key}: {e}")

    db['sprints'].update_one(
        {"_id": __import__('bson').ObjectId(sprint_id)},
        {"$set": {
            "jira_sync_enabled": True,
            "jira_sprint_id": jira_sprint_id,
            "last_jira_sync": __import__('datetime').datetime.utcnow().isoformat(),
        }}
    )

    return {"added": added, "skipped": skipped, "skipped_closed": skipped_closed,
            "total_jira": len(issues), "errors": errors}
