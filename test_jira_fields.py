"""Discover JIRA field IDs and test push operations.
Run: .venv/bin/python test_jira_fields.py"""
import requests

EMAIL = "ashish.awasthi@moglix.com"
API_TOKEN = "ATATT3xFfGF0NrWMsIFLBEDoLopsPURVeWdcFzls-_tZLdxTkkAyFP7b1p_68Q6Cbv93__2Ff7BFZz-M8-GJbvOmthYMpOAZLCVnAfPomVE13SBh8fAe8VPNnPcf_z2GzBH2ArnmWJ-42RnEMcgzN0MfVrdBifVEzPsDu8ceNYg_pktaPlktjYE=FE7B4C2B"
BASE_URL = "https://moglix.atlassian.net"

def find_all_fields():
    """Fetch all fields and list them"""
    url = f"{BASE_URL}/rest/api/2/field"
    print(f"Fetching all fields from {BASE_URL}...")

    resp = requests.get(url, auth=(EMAIL, API_TOKEN),
                        headers={"Accept": "application/json"}, timeout=30)
    if resp.status_code != 200:
        print(f"Failed: {resp.status_code} {resp.text[:300]}")
        return

    fields = resp.json()
    print(f"\nTotal fields: {len(fields)}")

    print("\n=== ALL CUSTOM FIELDS (customfield_*) ===")
    for f in sorted(fields, key=lambda x: x.get("id", "")):
        if f.get("id", "").startswith("customfield_"):
            print(f"  {f.get('id'):30s} = {f.get('name')}")

    print("\n=== FIELDS WITH 'story' or 'point' or 'estimate' ===")
    for f in fields:
        name = f.get("name", "").lower()
        if any(kw in name for kw in ["story", "point", "estimate", "sprint"]):
            print(f"  {f.get('id'):30s} = {f.get('name')}")

def check_issue_fields(issue_key):
    """Check which custom fields have values on a specific issue"""
    url = f"{BASE_URL}/rest/api/2/issue/{issue_key}"
    params = {"fields": "summary,assignee,status,issuetype,customfield_*"}

    resp = requests.get(url, auth=(EMAIL, API_TOKEN),
                        headers={"Accept": "application/json"},
                        params=params, timeout=30)
    if resp.status_code != 200:
        print(f"Failed: {resp.status_code} {resp.text[:300]}")
        return

    fields = resp.json().get("fields", {})
    print(f"\n=== Custom fields with VALUES on {issue_key} ===")
    for k, v in sorted(fields.items()):
        if k.startswith("customfield_") and v is not None:
            print(f"  {k}: {v}")

def test_story_points_push(issue_key, field_id, value):
    """Test setting a specific story points field"""
    url = f"{BASE_URL}/rest/api/2/issue/{issue_key}"
    payload = {"fields": {field_id: value}}

    print(f"\n=== Test: Set {field_id} = {value} on {issue_key} ===")
    resp = requests.put(url, auth=(EMAIL, API_TOKEN),
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                        json=payload, timeout=30)
    print(f"Status: {resp.status_code}")
    if resp.status_code in (200, 204):
        print("SUCCESS!")
    else:
        print(f"Failed: {resp.text[:500]}")

if __name__ == "__main__":
    print("JIRA Field Discovery & Push Test")
    print("1. List all custom field IDs with labels")
    print("2. Check which fields have values on a specific issue")
    print("3. Test setting a story points field")
    choice = input("\nChoose (1/2/3): ").strip()

    if choice == "1":
        find_all_fields()
    elif choice == "2":
        key = input("Enter issue key (e.g. CT-3524): ").strip()
        check_issue_fields(key)
    elif choice == "3":
        key = input("Enter issue key: ").strip()
        field_id = input("Enter field ID (e.g. customfield_10016): ").strip()
        value = float(input("Enter value to set (e.g. 3.0): ").strip())
        test_story_points_push(key, field_id, value)
