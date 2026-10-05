from utils.db import (
    get_mongo_db, get_current_team_id,
    get_user_jira_account_id, update_ticket_jira_push_status,
    get_ticket_comments, add_ticket_comment,
    get_jira_status_mapping, update_ticket_jira_status_push, update_sprint_jira_close_sync
)
from utils.jira_client import (
    update_issue_fields, add_comment, _base_url, DEFAULT_STORY_POINTS_FIELD,
    get_issue_status, find_transition_for_status, transition_issue
)


def push_ticket_to_jira(sprint_id, ticket_id, jira_key, assignee_name, sp,
                        story_points_field=None):
    if story_points_field is None:
        from utils.jira_client import DEFAULT_STORY_POINTS_FIELD
        story_points_field = DEFAULT_STORY_POINTS_FIELD
    """Push ticket updates to JIRA.

    Returns dict: {"status": "success"|"failed", "message": str, "pushed_comments": int}
    """
    tid = get_current_team_id()
    pushed_comments = 0

    try:
        # 1. Push assignee (match by name -> JIRA accountId)
        jira_account_id = get_user_jira_account_id(assignee_name)
        print(f"[JIRA PUSH] Pushing {jira_key}: assignee={assignee_name} (accountId={jira_account_id}), sp={sp}")
        if jira_account_id:
            update_issue_fields(jira_key, assignee_account_id=jira_account_id, story_points=sp,
                                story_points_field=story_points_field)
        else:
            # Push story points only if no assignee match
            print(f"[JIRA PUSH] No accountId for '{assignee_name}', pushing SP only")
            update_issue_fields(jira_key, story_points=sp,
                                story_points_field=story_points_field)

        # 2. Push unsynced local comments
        from utils.db import get_mongo_db as _get_db
        _db = _get_db()
        _tid = get_current_team_id()
        ticket_doc = _db['backlog'].find_one({
            "team_id": str(_tid),
            "sprint_id": str(sprint_id),
            "ticket_id": ticket_id
        })
        local_comments = ticket_doc.get("local_comments", []) if ticket_doc else []
        for idx, comment in enumerate(local_comments):
            if not comment.get("synced"):
                comment_body = f"**[{comment['author']}]**: {comment['body']}"
                print(f"[JIRA PUSH] Adding comment by {comment['author']}: {comment['body'][:50]}")
                add_comment(jira_key, comment_body)
                _db['backlog'].update_one(
                    {"team_id": str(_tid), "sprint_id": str(sprint_id), "ticket_id": ticket_id},
                    {"$set": {f"local_comments.{idx}.synced": True}}
                )
                pushed_comments += 1

        # 3. Update push status
        from datetime import datetime, timezone
        update_ticket_jira_push_status(
            str(sprint_id), ticket_id, "synced", datetime.now(timezone.utc).isoformat()
        )

        msg = "Ticket updated in JIRA."
        if pushed_comments > 0:
            msg += f" {pushed_comments} comment(s) synced."
        if not jira_account_id and assignee_name:
            msg += f" Assignee '{assignee_name}' not linked to JIRA (no account ID)."
        print(f"[JIRA PUSH] Success: {msg}")

        return {"status": "success", "message": msg, "pushed_comments": pushed_comments}

    except Exception as e:
        from datetime import datetime, timezone
        update_ticket_jira_push_status(
            str(sprint_id), ticket_id, "failed", datetime.now(timezone.utc).isoformat()
        )
        return {"status": "failed", "message": str(e), "pushed_comments": 0}


# --- STATUS PUSH ---

def _resolve_target_jira_status(ticket, mappings):
    """Determine target JIRA status from portal status fields and mapping config.

    Logic:
    - overall Done + all BE/FE/QA Done/NA → Done mapping
    - overall In Progress or some roles Done → In Progress mapping
    - otherwise → Todo mapping
    """
    overall = ticket.get("status", "Todo")
    be_status = ticket.get("backend_status", "NA") or "NA"
    fe_status = ticket.get("frontend_status", "NA") or "NA"
    qa_status = ticket.get("qa_status", "NA") or "NA"

    def _all_done():
        roles = [be_status, fe_status, qa_status]
        return all(s in ("Done", "NA") for s in roles) and any(s == "Done" for s in roles)

    def _any_done():
        return be_status == "Done" or fe_status == "Done" or qa_status == "Done"

    # Determine composite key
    if overall == "Done" or _all_done():
        portal_key = "Done"
    elif overall == "In Progress" or _any_done():
        portal_key = "In Progress"
    else:
        portal_key = "Todo"

    # Find matching mapping
    for m in mappings:
        if m.get("portal_status") == portal_key:
            return m.get("jira_status"), m.get("jira_transition_id")
    return None, None


def push_ticket_status_to_jira(sprint_id, ticket_id, jira_key, target_status,
                                transition_id=None, comment=None):
    """Push status change to JIRA via transitions API.

    Returns dict: {"status": "success"|"failed"|"no_transition"|"same_status", "message": str}
    """
    try:
        current_jira_status = get_issue_status(jira_key)
        if current_jira_status.lower() == target_status.lower():
            return {"status": "same_status", "message": f"Already in status '{target_status}'"}

        if not transition_id:
            transition_id = find_transition_for_status(jira_key, target_status)

        if not transition_id:
            from utils.jira_client import get_issue_transitions
            available = get_issue_transitions(jira_key)
            available_names = [t.get("to", {}).get("name", "?") for t in available]
            update_ticket_jira_status_push(
                sprint_id, ticket_id, current_jira_status, target_status,
                False, f"No transition to '{target_status}'. Available: {available_names}"
            )
            return {
                "status": "no_transition",
                "message": f"No transition to '{target_status}' from '{current_jira_status}'. "
                          f"Available: {available_names}"
            }

        transition_comment = comment or f"Status changed to '{target_status}' (via Agile Portal)"
        transition_issue(jira_key, transition_id, comment=transition_comment)

        update_ticket_jira_status_push(sprint_id, ticket_id, current_jira_status, target_status, True)

        db = get_mongo_db()
        tid = get_current_team_id()
        db['backlog'].update_one(
            {"team_id": str(tid), "sprint_id": str(sprint_id), "ticket_id": ticket_id},
            {"$set": {"jira_status": target_status}}
        )

        return {"status": "success", "message": f"Transitioned to '{target_status}' in JIRA"}

    except Exception as e:
        current = current_jira_status if 'current_jira_status' in dir() else "unknown"
        update_ticket_jira_status_push(sprint_id, ticket_id, current, target_status, False, str(e))
        return {"status": "failed", "message": str(e)}


def push_all_statuses_on_sprint_close(sprint_id, dry_run=False):
    """Push all ticket statuses to JIRA when closing a sprint.

    Returns dict: Summary of push results
    """
    tid = get_current_team_id()
    db = get_mongo_db()

    mapping_doc = get_jira_status_mapping(str(tid))
    if not mapping_doc:
        update_sprint_jira_close_sync(sprint_id, "no_mapping")
        return {"status": "no_mapping", "message": "No status mapping configured.", "total": 0}

    tickets = list(db['backlog'].find({"team_id": str(tid), "sprint_id": str(sprint_id)}))

    results = {"total": 0, "pushed": 0, "skipped": 0, "failed": 0, "same_status": 0, "details": []}

    for ticket in tickets:
        if not ticket.get("jira_key"):
            continue
        results["total"] += 1
        jira_key = ticket["jira_key"]

        target_status, transition_id = _resolve_target_jira_status(
            ticket, mapping_doc.get("mappings", [])
        )

        if not target_status:
            results["skipped"] += 1
            results["details"].append({
                "ticket_id": ticket["ticket_id"],
                "jira_key": jira_key,
                "status": "skipped",
                "reason": "No mapping for current portal status",
            })
            continue

        if dry_run:
            results["details"].append({
                "ticket_id": ticket["ticket_id"],
                "jira_key": jira_key,
                "status": "would_push",
                "target": target_status,
            })
            continue

        push_result = push_ticket_status_to_jira(
            str(sprint_id), ticket["ticket_id"], jira_key,
            target_status, transition_id
        )

        key = push_result["status"]
        if key == "same_status":
            results["same_status"] += 1
        elif key == "success":
            results["pushed"] += 1
        else:
            results["failed"] += 1
        results["details"].append({
            "ticket_id": ticket["ticket_id"],
            "jira_key": jira_key,
            **push_result,
        })

    update_sprint_jira_close_sync(sprint_id, "completed" if not dry_run else "dry_run", results)
    return results


def _mark_comment_synced(sprint_id, ticket_id, comment):
    """Mark a local comment as synced to JIRA."""
    db = get_mongo_db()
    tid = get_current_team_id()
    db['backlog'].update_one(
        {
            "team_id": str(tid),
            "sprint_id": str(sprint_id),
            "ticket_id": ticket_id,
            "local_comments": {"$elemMatch": {
                "author": comment.get("author"),
                "body": comment.get("body"),
                "created": comment.get("created"),
            }}
        },
        {"$set": {"local_comments.$.synced": True}}
    )
