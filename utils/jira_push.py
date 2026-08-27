from utils.db import (
    get_mongo_db, get_current_team_id,
    get_user_jira_account_id, update_ticket_jira_push_status,
    get_ticket_comments, add_ticket_comment
)
from utils.jira_client import update_issue_fields, add_comment, _base_url, DEFAULT_STORY_POINTS_FIELD


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
