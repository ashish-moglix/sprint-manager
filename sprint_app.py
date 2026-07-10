import streamlit as st
from utils.db import init_db

# Always set page config as the first Streamlit command
st.set_page_config(
    page_title="EM Sprint Cockpit",
    page_icon=":material/analytics:",
    layout="wide"
)

# Initialize database schemas and default team members if not already populated
init_db()

# Professional sidebar branding logo
st.logo("logo.png")

# Main page routing definition
pg = st.navigation([
    st.Page("app_pages/dashboard.py", title="Dashboard", icon=":material/dashboard:"),
    st.Page("app_pages/sprint_planning.py", title="Sprint Planning", icon=":material/assignment:"),
    st.Page("app_pages/team_capacity.py", title="Team Capacity", icon=":material/groups:"),
    st.Page("app_pages/presence_holidays.py", title="Presence & Holidays", icon=":material/calendar_today:"),
    st.Page("app_pages/team_system_setup.py", title="Team & System Setup", icon=":material/settings:"),
])

pg.run()
