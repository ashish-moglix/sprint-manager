import os
import requests
import streamlit as st

DEFAULT_STORY_POINTS_FIELD = "customfield_10119"


def _get_auth():
    """Return (email, access_token) — reads from encrypted DB storage."""
    from utils.db import get_jira_credentials
    creds = get_jira_credentials()
    if not creds or not creds.get("token") or not creds.get("email"):
        raise RuntimeError("JIRA credentials not configured. Please configure in Super Admin > JIRA Configuration.")
    return creds["email"], creds["token"]


def _headers():
    return {"Accept": "application/json", "Content-Type": "application/json"}


def _auth():
    email, token = _get_auth()
    return (email, token)


def _base_url():
    """Get base URL from encrypted DB storage."""
    from utils.db import get_jira_credentials
    creds = get_jira_credentials()
    if not creds or not creds.get("base_url"):
        raise RuntimeError("JIRA base URL not configured. Please configure in Super Admin > JIRA Configuration.")
    return creds["base_url"].rstrip("/")


def get_story_points_field():
    """Get the story points custom field ID from DB or default."""
    try:
        from utils.db import get_jira_credentials
        creds = get_jira_credentials()
        if creds and creds.get("story_points_field"):
            return creds["story_points_field"]
    except Exception:
        pass
    return DEFAULT_STORY_POINTS_FIELD


def get_jira_field(field_name):
    """Get a specific JIRA custom field ID from DB credentials.

    Args:
        field_name: One of 'story_points', 'start_date', 'end_date', 'actual_sp'

    Returns:
        The field ID string or None
    """
    try:
        from utils.db import get_jira_credentials
        creds = get_jira_credentials()
        if creds:
            field_map = {
                "story_points": creds.get("story_points_field"),
                "start_date": creds.get("start_date_field"),
                "end_date": creds.get("end_date_field"),
                "actual_sp": creds.get("actual_sp_field"),
            }
            return field_map.get(field_name)
    except Exception:
        pass
    return None


def get_all_jira_fields():
    """Get all JIRA field configurations from DB.

    Returns:
        dict with field_name -> field_id mapping, or None if not configured
    """
    try:
        from utils.db import get_jira_credentials
        creds = get_jira_credentials()
        if creds:
            return {
                "story_points": creds.get("story_points_field"),
                "start_date": creds.get("start_date_field"),
                "end_date": creds.get("end_date_field"),
                "actual_sp": creds.get("actual_sp_field"),
            }
    except Exception:
        pass
    return None


# --- READ OPERATIONS ---

def get_sprints_by_board(board_id, state="active,closed,future"):
    """Fetch all sprints for a given board. Returns list of sprint dicts."""
    url = f"{_base_url()}/rest/agile/1.0/board/{board_id}/sprint"
    params = {"state": state}
    resp = requests.get(url, auth=_auth(), headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("values", [])


def find_sprint_by_name(board_id, sprint_name):
    """Find a sprint by name on a board. Returns sprint dict or None."""
    sprints = get_sprints_by_board(board_id)
    for s in sprints:
        if s.get("name", "").strip().lower() == sprint_name.strip().lower():
            return s
    return None


def get_issues_by_sprint(board_id, sprint_id, story_points_field="customfield_10119"):
    """Fetch all issues in a sprint including subtasks.

    Uses Agile REST for top-level issues, then extracts subtask keys from
    each issue's 'subtasks' field and fetches them individually.
    This avoids the unreliable /rest/api/2/search endpoint.
    """
    fields = f"summary,description,assignee,status,issuetype,timetracking,subtasks,{story_points_field}"
    top_level = _get_issues_by_sprint_agile(board_id, sprint_id, story_points_field, extra_fields="subtasks")

    all_issues = list(top_level)
    subtask_keys = []

    for issue in top_level:
        fields_data = issue.get("fields", {}) or {}
        subtasks_list = fields_data.get("subtasks", []) or []
        for st in subtasks_list:
            st_key = st.get("key")
            if st_key:
                subtask_keys.append(st_key)

    print(f"[JIRA DEBUG] Agile REST returned {len(top_level)} top-level, found {len(subtask_keys)} subtask keys")

    for st_key in subtask_keys:
        issue_data = get_issue_by_key(st_key, story_points_field)
        if issue_data:
            all_issues.append(issue_data)

    return all_issues


def _get_issues_by_sprint_agile(board_id, sprint_id, story_points_field, extra_fields=""):
    """Fetch top-level issues from Agile REST endpoint (no subtasks by default)."""
    fields = f"summary,description,assignee,status,issuetype,timetracking,{story_points_field}"
    if extra_fields:
        fields += f",{extra_fields}"
    url = f"{_base_url()}/rest/agile/1.0/board/{board_id}/sprint/{sprint_id}/issue"
    params = {"maxResults": 200, "fields": fields}
    resp = requests.get(url, auth=_auth(), headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("issues", [])


def get_issue_by_key(issue_key, story_points_field="customfield_10119"):
    """Fetch a single issue by key including its subtask/parent fields."""
    url = f"{_base_url()}/rest/api/2/issue/{issue_key}"
    params = {"fields": f"summary,description,assignee,status,issuetype,timetracking,parent,subtasks,{story_points_field}"}
    resp = requests.get(url, auth=_auth(), headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()




def get_comments(issue_key):
    """Fetch all comments for an issue. Returns list of comment dicts."""
    url = f"{_base_url()}/rest/api/2/issue/{issue_key}/comment"
    resp = requests.get(url, auth=_auth(), headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("comments", [])


def search_user_by_email(email):
    """Search for a JIRA user by email. Returns user dict or None."""
    url = f"{_base_url()}/rest/api/2/user/search"
    params = {"query": email, "maxResults": 5}
    resp = requests.get(url, auth=_auth(), headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    users = resp.json()
    if isinstance(users, list) and users:
        for u in users:
            if u.get("emailAddress", "").lower() == email.lower():
                return u
        return users[0]
    return None


# --- WRITE OPERATIONS ---

def update_issue_fields(issue_key, assignee_account_id=None, story_points=None, story_points_field="customfield_10119"):
    """Update issue fields. Only sends fields that are provided."""
    url = f"{_base_url()}/rest/api/2/issue/{issue_key}"
    fields = {}
    if assignee_account_id:
        fields["assignee"] = {"accountId": assignee_account_id}
    if story_points is not None:
        fields[story_points_field] = story_points

    if not fields:
        return

    print(f"[JIRA API] PUT {url} payload={{'fields': {fields}}}")
    resp = requests.put(url, auth=_auth(), headers=_headers(), json={"fields": fields}, timeout=30)
    print(f"[JIRA API] Response: {resp.status_code} body={resp.text[:500]}")
    resp.raise_for_status()


def add_comment(issue_key, comment_body):
    """Add a comment to an issue. Returns the created comment dict."""
    url = f"{_base_url()}/rest/api/2/issue/{issue_key}/comment"
    resp = requests.post(url, auth=_auth(), headers=_headers(), json={"body": comment_body}, timeout=30)
    resp.raise_for_status()
    return resp.json()


# --- PARSING ---

def _extract_text_from_adf(node):
    """Recursively extract plain text from Atlassian Document Format (ADF)."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    texts = []
    if node.get("type") == "text":
        return node.get("text", "")
    for child in node.get("content", []):
        texts.append(_extract_text_from_adf(child))
    separator = "\n" if node.get("type") in ("paragraph", "heading", "blockquote", "listItem") else ""
    return separator.join(t for t in texts if t)


def _parse_description(raw):
    """Parse description from JIRA - handles both plain string and ADF dict."""
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return _extract_text_from_adf(raw)
    return str(raw)


def parse_issue(issue, base_url, story_points_field="customfield_10119"):
    """Parse a JIRA issue into a flat dict for our backlog schema."""
    fields = issue.get("fields", {})
    assignee = fields.get("assignee") or {}
    issue_type = fields.get("issuetype", {}) or {}
    status = fields.get("status", {}) or {}
    parent = fields.get("parent", {}) or {}

    sp = (fields.get(story_points_field)
          or fields.get("customfield_10016")
          or fields.get("customfield_10020")
          or fields.get("customfield_10002")
          or 0)
    try:
        sp = float(sp)
    except (TypeError, ValueError):
        sp = 0.0

    return {
        "jira_key": issue.get("key"),
        "jira_url": f"{base_url}/browse/{issue.get('key')}",
        "title": fields.get("summary", ""),
        "description": _parse_description(fields.get("description")),
        "assignee": assignee.get("displayName", ""),
        "assignee_email": assignee.get("emailAddress", ""),
        "assignee_account_id": assignee.get("accountId", ""),
        "role": "",
        "category": "New Work",
        "sp": sp,
        "jira_status": status.get("name", ""),
        "issue_type": issue_type.get("name", ""),
        "parent_key": parent.get("key", ""),
    }


def parse_comment(comment):
    """Parse a JIRA comment into our local format."""
    author = comment.get("author", {}) or {}
    return {
        "author": author.get("displayName", ""),
        "email": author.get("emailAddress", ""),
        "body": comment.get("body", ""),
        "created": comment.get("created", ""),
        "source": "jira",
    }
