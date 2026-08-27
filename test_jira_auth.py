"""Quick test to verify JIRA credentials work. Run: .venv/bin/python test_jira_auth.py"""
import requests

EMAIL = "your-email-address-for-jira"
API_TOKEN = "your-api-access-token-for-jira"
BASE_URL = "your-jira-base-url"  # e.g., https://yourcompany.atlassian.net
BOARD_ID = "your-jira-board-id"  # e.g., 1234

def _base_url():
    return BASE_URL.rstrip("/")

def test_basic_auth():
    """Test with Basic Auth (email:token) — standard API tokens"""
    url = f"{_base_url()}/rest/agile/1.0/board/{BOARD_ID}/sprint"
    params = {"state": "active,closed,future"}
    print("=== Test 1: Basic Auth (email:token) ===")
    print(f"URL: {url}")
    resp = requests.get(url, auth=(EMAIL, API_TOKEN),
                        headers={"Accept": "application/json"},
                        params=params, timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        sprints = resp.json().get("values", [])
        print(f"SUCCESS! Found {len(sprints)} sprints")
        return True
    else:
        print(f"Failed: {resp.text[:300]}")
        return False

def test_bearer_auth():
    """Test with Bearer token — OAuth / scoped API tokens"""
    url = f"{_base_url()}/rest/agile/1.0/board/{BOARD_ID}/sprint"
    params = {"state": "active,closed,future"}
    print("\n=== Test 2: Bearer Auth (Authorization: Bearer) ===")
    print(f"URL: {url}")
    resp = requests.get(url,
                        headers={"Accept": "application/json",
                                 "Authorization": f"Bearer {API_TOKEN}"},
                        params=params, timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        sprints = resp.json().get("values", [])
        print(f"SUCCESS! Found {len(sprints)} sprints")
        for s in sprints:
            print(f"  - {s.get('name')} (id={s.get('id')}, state={s.get('state')})")
        return True
    else:
        print(f"Failed: {resp.text[:300]}")
        return False

def test_user_search():
    """Test a simpler endpoint to isolate the issue"""
    url = f"{_base_url()}/rest/api/2/myself"
    print("\n=== Test 3: Basic Auth - /myself endpoint ===")
    resp = requests.get(url, auth=(EMAIL, API_TOKEN),
                        headers={"Accept": "application/json"}, timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"SUCCESS! Logged in as: {data.get('displayName')} ({data.get('emailAddress')})")
    else:
        print(f"Failed: {resp.text[:300]}")

    print("\n=== Test 4: Bearer Auth - /myself endpoint ===")
    resp = requests.get(url,
                        headers={"Accept": "application/json",
                                 "Authorization": f"Bearer {API_TOKEN}"},
                        timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"SUCCESS! Logged in as: {data.get('displayName')} ({data.get('emailAddress')})")
    else:
        print(f"Failed: {resp.text[:300]}")

if __name__ == "__main__":
    test_basic_auth()
    test_bearer_auth()
    test_user_search()
