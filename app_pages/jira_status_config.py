import streamlit as st
import pandas as pd
from utils.db import (
    get_jira_status_mapping, save_jira_status_mapping,
    get_team_jira_sync_settings, update_team_jira_sync_settings,
    get_current_team_id
)

st.set_page_config(page_title="JIRA Status Mapping", page_icon=":material/sync:", layout="wide")

if not st.session_state.get("user"):
    st.warning("Please log in to access this page.")
    st.stop()

user_role = st.session_state.user.get('user_role', 'Team User')
if user_role not in ('Team Admin', 'Super Admin'):
    st.warning("Only team admins can configure JIRA status mappings.")
    st.stop()

st.title("JIRA Status Mapping")
st.caption("Configure how portal statuses map to JIRA statuses for bi-directional sync")

tid = st.session_state.user.get("team_id")
if not tid:
    st.error("No team associated with your account.")
    st.stop()

mapping_doc = get_jira_status_mapping(str(tid)) or {}
sync_settings = get_team_jira_sync_settings(str(tid))

# --- How it works ---
with st.expander(":material/help: How status sync works", expanded=False):
    st.markdown("""
**Sync direction: Portal → JIRA**

When you push status to JIRA (manually from ticket details, or automatically on sprint close),
the portal looks at the ticket's status fields and decides which JIRA status to transition to.

**How portal status is resolved to a single composite key:**

| Portal overall status | BE / FE / QA roles                    | Composite key used for mapping |
|-----------------------|---------------------------------------|--------------------------------|
| Done                  | All Done or NA                        | **Done**                       |
| Done                  | Some In Progress (rest Done/NA)       | **Done** (overall wins)        |
| In Progress           | Any Done or In Progress               | **In Progress**                |
| In Progress                                   | All Todo/NA                   | **In Progress**                |
| Todo                 | All Todo/NA                           | **Todo**                       |

So the mapping table only needs 3 rows — one per composite key.

**What happens when you push:**

1. Portal determines composite key (e.g. `In Progress`)
2. Looks up your mapping to find target JIRA status (e.g. `In Development`)
3. Fetches available JIRA transitions for that issue
4. Finds the transition whose destination matches the target status name
5. Executes the transition via JIRA API

**Important:** The target JIRA status must be reachable via a transition from the issue's
current status. If it's not, the push will fail with a list of available transitions.
Use the Test Connection section below to verify.
""")

# --- Sync Settings ---
with st.container(border=True):
    st.subheader(":material/tune: Sync Settings")

    c1, c2 = st.columns(2)
    with c1:
        skip_closed = st.checkbox(
            "Skip closed JIRA tickets during sync",
            value=sync_settings.get("skip_closed_on_sync", True),
            help="Tickets with Done/Closed/Resolved status in JIRA will not be imported"
        )
    with c2:
        auto_sync_close = st.checkbox(
            "Auto-push statuses on sprint close",
            value=sync_settings.get("auto_sync_on_close", True),
            help="When closing a sprint, all ticket statuses are pushed back to JIRA"
        )

    if st.button("Save Sync Settings", key="save_sync_settings"):
        update_team_jira_sync_settings(
            tid,
            skip_closed_on_sync=skip_closed,
            auto_sync_on_close=auto_sync_close
        )
        st.success("Sync settings saved.")

# --- Skip Statuses ---
with st.container(border=True):
    st.subheader(":material/block: Skip on Import (JIRA → Portal)")
    st.markdown("JIRA tickets with these statuses will **not** be imported during sprint sync.")
    st.caption("This prevents cluttering your sprint with already-finished work.")

    skip_statuses_str = ", ".join(mapping_doc.get("skip_statuses", ["Done", "Closed", "Resolved"]))
    skip_statuses_input = st.text_input(
        "Comma-separated JIRA status names",
        value=skip_statuses_str,
        help="Case-insensitive. Must match your JIRA workflow status names exactly."
    )

    if st.button("Save Skip Statuses", key="save_skip_statuses"):
        skip_list = [s.strip() for s in skip_statuses_input.split(",") if s.strip()]
        existing_mappings = mapping_doc.get("mappings", [])
        save_jira_status_mapping(tid, existing_mappings, skip_list)
        st.success(f"Will skip tickets with JIRA status: {skip_list}")

# --- Status Mapping Editor ---
with st.container(border=True):
    st.subheader(":material/swap_horiz: Status Mapping (Portal → JIRA)")
    st.markdown("""
Map each composite portal status to the JIRA status you want to transition to.
The **JIRA Status** must be the exact name of a status in your JIRA workflow.
""")

    portal_statuses = ["Todo", "In Progress", "Done"]
    status_descriptions = {
        "Todo": "Ticket is in Todo (no work started, or all roles are Todo/NA)",
        "In Progress": "Overall In Progress, or at least one role (BE/FE/QA) is Done",
        "Done": "Overall Done, or all active roles (BE/FE/QA) are Done/NA",
    }
    existing_mappings = mapping_doc.get("mappings", [])

    mapping_data = []
    for portal_st in portal_statuses:
        existing = next((m for m in existing_mappings if m.get("portal_status") == portal_st), {})
        mapping_data.append({
            "portal_status": portal_st,
            "description": status_descriptions[portal_st],
            "jira_status": existing.get("jira_status", ""),
            "jira_transition_id": existing.get("jira_transition_id", ""),
        })

    edited_mappings = st.data_editor(
        pd.DataFrame(mapping_data),
        column_config={
            "portal_status": st.column_config.TextColumn(
                "Portal Status", disabled=True, width="small"
            ),
            "description": st.column_config.TextColumn(
                "When this applies", disabled=True, width="medium"
            ),
            "jira_status": st.column_config.TextColumn(
                "Target JIRA Status *",
                help="Exact JIRA status name — must exist in your JIRA workflow"
            ),
            "jira_transition_id": st.column_config.TextColumn(
                "Transition ID (optional)",
                help="Leave blank to auto-resolve. Fill only if auto-detection fails."
            ),
        },
        key="status_mapping_editor",
        hide_index=True,
        num_rows="fixed",
        use_container_width=True,
    )

    col_save, col_autofill = st.columns([1, 1])
    with col_save:
        if st.button("Save Status Mappings", type="primary", key="save_mappings", use_container_width=True):
            mappings_list = edited_mappings.to_dict("records")
            mappings_list = [m for m in mappings_list if m.get("jira_status", "").strip()]
            save_jira_status_mapping(
                tid, mappings_list,
                mapping_doc.get("skip_statuses", ["Done", "Closed", "Resolved"])
            )
            st.success(f"Saved {len(mappings_list)} status mappings.")

    with col_autofill:
        # Auto-fill transition IDs from a real JIRA issue
        st.caption("Tip: Use Test Connection below to find transition IDs, or leave blank for auto-detection.")

# --- Test Connection & Transition Finder ---
with st.container(border=True):
    st.subheader(":material/cable: Test Connection & Find Transitions")
    st.markdown("""
Enter any active JIRA issue key from your board. This will:
1. Verify your JIRA credentials work
2. Show the issue's current status
3. List all available transitions (with IDs) — use these to fill the mapping table above
""")

    test_key = st.text_input(
        "JIRA Issue Key", placeholder="e.g. CREDLIX-123", key="test_issue_key"
    )

    if st.button("Fetch Available Transitions", type="primary", key="test_transitions") and test_key.strip():
        from utils.jira_client import get_issue_transitions, get_issue_status
        try:
            current = get_issue_status(test_key.strip())
            st.markdown(f"**Current JIRA status:** `{current}`")

            transitions = get_issue_transitions(test_key.strip())
            if transitions:
                st.markdown("**Available transitions from current status:**")
                trans_data = []
                for t in transitions:
                    trans_data.append({
                        "Transition Name": t["name"],
                        "Target Status": t["to"]["name"],
                        "Transition ID": t["id"],
                    })
                st.dataframe(pd.DataFrame(trans_data), hide_index=True, use_container_width=True)
                st.caption("Copy the **Target Status** name into your mapping table's 'Target JIRA Status' column.")
            else:
                st.info("No transitions available — issue may be in a terminal status.")
        except Exception as e:
            st.error(f"Failed: {e}")

# --- Current Config Summary ---
with st.container(border=True):
    st.subheader(":material/summary: Current Configuration Summary")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Skip closed on sync:** {'✅ Yes' if skip_closed else '❌ No'}")
        st.markdown(f"**Auto-sync on close:** {'✅ Yes' if auto_sync_close else '❌ No'}")
    with col2:
        st.markdown(f"**Skip statuses:** `{skip_statuses_input}`")

    st.markdown("**Active push mappings:**")
    active = edited_mappings[edited_mappings["jira_status"].str.strip() != ""]
    if active.empty:
        st.caption("⚠️ No mappings configured. Status push will be skipped.")
    else:
        for _, row in active.iterrows():
            st.markdown(
                f"- Portal **`{row['portal_status']}`** → JIRA **`{row['jira_status']}`**"
                f"· transition: `{row['jira_transition_id'] or 'auto-detect'}`"
            )
