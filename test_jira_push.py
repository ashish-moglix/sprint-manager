"""Test JIRA push operations. Run: .venv/bin/python test_jira_push.py"""
import requests

EMAIL = "ashish.awasthi@moglix.com"
API_TOKEN = "PASTE_YOUR_WORKING_TOKEN_HERE"
BASE_URL = "https://moglix.atlassian.net"

def test_update_issue():
    """Test updating story points on a ticket"""
    issue_key = input("Enter JIRA issue key to test (e.g. CREDLIX-123): ").strip()
    url = f"{BASE_URL}/rest/api/2/issue/{issue_key}"

    print(f"\n=== Test: Update story points on {issue_key} ===")
    print(f"URL: {url}")
    print(f"Payload: {{'fields': {{'customfield_10016': 3.0}}}}")

    resp = requests.put(url, auth=(EMAIL, API_TOKEN),
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                        json={"fields": {"customfield_10016": 3.0}},
                        timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.status_code in (200, 204):
        print("SUCCESS! Issue updated (204 = no content, which is normal)")
    else:
        print(f"Failed: {resp.text[:500]}")

def test_add_comment():
    """Test adding a comment to a ticket"""
    issue_key = input("\nEnter JIRA issue key for comment test: ").strip()
    url = f"{BASE_URL}/rest/api/2/issue/{issue_key}/comment"

    print(f"\n=== Test: Add comment to {issue_key} ===")
    comment_body = "[Test User]: This is a test comment from sprint manager"

    resp = requests.post(url, auth=(EMAIL, API_TOKEN),
                         headers={"Accept": "application/json", "Content-Type": "application/json"},
                         json={"body": comment_body},
                         timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 201:
        data = resp.json()
        print(f"SUCCESS! Comment added. ID: {data.get('id')}")
    else:
        print(f"Failed: {resp.text[:500]}")

def test_get_issue():
    """Test fetching an issue to verify fields"""
    issue_key = input("\nEnter JIRA issue key to fetch: ").strip()
    url = f"{BASE_URL}/rest/api/2/issue/{issue_key}"
    params = {"fields": "summary,assignee,status,customfield_10016"}

    resp = requests.get(url, auth=(EMAIL, API_TOKEN),
                        headers={"Accept": "application/json"},
                        params=params, timeout=30)
    print(f"\nStatus: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        fields = data.get("fields", {})
        print(f"Summary: {fields.get('summary')}")
        print(f"Assignee: {fields.get('assignee', {}).get('displayName')}")
        print(f"Assignee Email: {fields.get('assignee', {}).get('emailAddress')}")
        print(f"Assignee AccountId: {fields.get('assignee', {}).get('accountId')}")
        print(f"Status: {fields.get('status', {}).get('name')}")
        print(f"Story Points (customfield_10016): {fields.get('customfield_10016')}")
    else:
        print(f"Failed: {resp.text[:500]}")

if __name__ == "__main__":
    print("JIRA Push Test Utility")
    print("1. Test update issue fields")
    print("2. Test add comment")
    print("3. Test get issue details")
    choice = input("\nChoose (1/2/3): ").strip()
    if choice == "1":
        test_update_issue()
    elif choice == "2":
        test_add_comment()
    elif choice == "3":
        test_get_issue()
