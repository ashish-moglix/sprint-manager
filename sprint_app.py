import streamlit as st
import os
from utils.db import init_db, get_mongo_db
from utils.auth import create_token, decode_token, change_user_password
from utils.hash import hash_password
from bson import ObjectId
import urllib.parse
from http.cookies import SimpleCookie

# Always set page config as the first Streamlit command
st.set_page_config(
    page_title="EM Sprint Cockpit",
    page_icon=":material/analytics:",
    layout="wide"
)

# Initialize database schemas and default team members/sprint tenants
init_db()

# Logo is rendered customly in the sidebar top


# Initialize session state variables
if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None

def get_token_from_cookies() -> str | None:
    headers = st.context.headers
    cookie_str = headers.get("cookie") or headers.get("Cookie") or ""
    cookie = SimpleCookie()
    cookie.load(cookie_str)
    if "sprint_cockpit_token" in cookie:
        return urllib.parse.unquote(cookie["sprint_cockpit_token"].value)
    return None

def get_theme_from_cookies() -> str:
    headers = st.context.headers
    cookie_str = headers.get("cookie") or headers.get("Cookie") or ""
    cookie = SimpleCookie()
    cookie.load(cookie_str)
    if "sprint_cockpit_theme" in cookie:
        val = cookie["sprint_cockpit_theme"].value
        return val if val in ("light", "dark") else "light"
    return "light"

if "theme" not in st.session_state:
    st.session_state.theme = get_theme_from_cookies()

# Read token from cookies if not in session state
if not st.session_state.user:
    cookie_token = get_token_from_cookies()
    if cookie_token:
        user_payload = decode_token(cookie_token)
        if user_payload:
            st.session_state.token = cookie_token
            st.session_state.user = user_payload
        else:
            st.error("Session expired or invalid authentication. Please log in again.", icon=":material/error:")
            # Clear expired cookie and entire localStorage
            st.markdown("""
                <svg style="display:none;"><script>
                    document.cookie = 'sprint_cockpit_token=; path=/; max-age=0; SameSite=Lax';
                    localStorage.clear();
                </script></svg>
            """, unsafe_allow_html=True)
    else:
        # If no token in cookies (and not logged in), check if there is a token in localStorage
        st.markdown("""
            <svg style="display:none;"><script>
                const token = localStorage.getItem('sprint_cockpit_token');
                if (token) {
                    document.cookie = 'sprint_cockpit_token=' + token + '; path=/; max-age=86400; SameSite=Lax';
                    location.reload();
                }
            </script></svg>
        """, unsafe_allow_html=True)

# Restore theme from localStorage into a cookie so Python can read it on next load
if "theme" not in st.session_state or st.session_state.theme == "light":
    st.markdown("""
        <svg style="display:none;"><script>
            var saved = localStorage.getItem('sprint_cockpit_theme');
            if (saved && saved !== 'light') {
                document.cookie = 'sprint_cockpit_theme=' + saved + '; path=/; max-age=86400; SameSite=Lax';
                location.reload();
            }
        </script></svg>
    """, unsafe_allow_html=True)


# Custom styling for premium aesthetic
st.markdown("""
    <style>
        /* Center container adjustments */
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .login-title {
            font-size: 2.25rem;
            font-weight: 700;
            color: var(--text-color);
            margin: 0;
            letter-spacing: -0.025em;
        }
        .login-subtitle {
            font-size: 0.95rem;
            color: #64748b;
            margin-top: 0.5rem;
            margin-bottom: 0;
        }
        /* Muted note at the bottom */
        .login-footer {
            text-align: center;
            font-size: 0.8rem;
            color: #94a3b8;
            margin-top: 1.5rem;
        }
    </style>
""", unsafe_allow_html=True)

# Authentication login flow
if not st.session_state.user:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1.3, 1.4, 1.3])
    with col2:
        # Centered Logo Section
        l_col1, l_col2, l_col3 = st.columns([1.2, 1.6, 1.2])
        with l_col2:
            st.image("logo.png", use_container_width=True)
            
        # Header Section
        st.markdown("""
            <div class="login-header">
                <h1 class="login-title">EM Sprint Cockpit</h1>
                <p class="login-subtitle">Enterprise agile capacity & backlog tracker</p>
            </div>
        """, unsafe_allow_html=True)
        
        # Main Login Box
        with st.container(border=True):
            st.markdown("<h3 style='margin-top:0; font-weight:600;'>Sign in</h3>", unsafe_allow_html=True)
            
            email_input = st.text_input("Email", placeholder="e.g. name@moglix.com", key="login_email_input")
            pass_input = st.text_input("Password", type="password", placeholder="••••••••", key="login_pass_input")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Sign in", type="primary", use_container_width=True):
                if email_input.strip() and pass_input:
                    db = get_mongo_db()
                    user = db['users'].find_one({"email": email_input.strip().lower()})
                    if user and user['password'] == hash_password(pass_input):
                        user_data = {
                            "id": str(user['_id']),
                            "name": user['name'],
                            "email": user['email'],
                            "user_role": user['user_role'],
                            "team_id": user.get('team_id')
                        }
                        # Generate and store JWT token
                        token = create_token(user_data)
                        
                        # Store in browser Cookies and reload to apply session (via parent SVG script)
                        st.markdown(f"""
                            <svg style="display:none;"><script>
                                localStorage.setItem('sprint_cockpit_token', '{token}');
                                document.cookie = 'sprint_cockpit_token={token}; path=/; max-age=86400; SameSite=Lax';
                                location.reload();
                            </script></svg>
                        """, unsafe_allow_html=True)
                        st.stop()
                    else:
                        st.error("Invalid email or password.", icon=":material/error:")
                else:
                    st.error("Please enter both email and password.", icon=":material/error:")

        # Footer Muted Text
        st.markdown("""
            <p class="login-footer">
                For account recovery or access issues, please contact your system administrator.
            </p>
        """, unsafe_allow_html=True)
else:
    # 1. Render Top of Sidebar: Logo & App Name
    logo_col1, logo_col2, logo_col3 = st.sidebar.columns([1.2, 1.6, 1.2])
    with logo_col2:
        st.image("logo.png", use_container_width=True)
        
    st.sidebar.markdown(
        """
        <div style="text-align: center; margin-bottom: 1rem;">
            <h2 style="font-weight: 700; font-size: 1.35rem; margin: 0;">EM Sprint Cockpit</h2>
            <p style="font-size: 0.8rem; color: #64748b; margin: 0;">Enterprise Agile Tracker</p>
        </div>
        <hr style="margin-top: 0.5rem; margin-bottom: 1rem;">
        """,
        unsafe_allow_html=True
    )

    # 1b. Render theme toggle
    is_dark = st.session_state.theme == "dark"
    theme_icon = "🌙" if not is_dark else "☀️"
    theme_label = "Dark mode" if not is_dark else "Light mode"
    if st.sidebar.button(f"{theme_icon} {theme_label}", use_container_width=True, key="theme_toggle"):
        st.session_state.theme = "dark" if not is_dark else "light"
        st.rerun()

    # Apply theme via JavaScript — sets Streamlit's own CSS custom properties on the root element.
    # This is more reliable than CSS injection because it works at the variable level.
    _theme_val = st.session_state.theme
    st.markdown(f"""
    <svg style="display:none;"><script>
    (function() {{
        var isDark = "{_theme_val}" === "dark";
        var root = document.documentElement;
        if (isDark) {{
            root.setAttribute("data-theme", "dark");
            root.style.setProperty("--background-color", "#0f172a");
            root.style.setProperty("--secondary-background-color", "#1e293b");
            root.style.setProperty("--text-color", "#f1f5f9");
            root.style.setProperty("--primary-color", "#60a5fa");
            root.style.setProperty("--link-color", "#60a5fa");
        }} else {{
            root.setAttribute("data-theme", "light");
            root.style.removeProperty("--background-color");
            root.style.removeProperty("--secondary-background-color");
            root.style.removeProperty("--text-color");
            root.style.removeProperty("--primary-color");
            root.style.removeProperty("--link-color");
        }}
        localStorage.setItem("sprint_cockpit_theme", "{_theme_val}");
    }})();
    </script></svg>
    """, unsafe_allow_html=True)


    if st.session_state.user['user_role'] == 'Super Admin':
        pg = st.navigation([
            st.Page("app_pages/super_admin.py", title="Super Admin Console", icon=":material/admin_panel_settings:")
        ])
    else:
        pg = st.navigation([
            st.Page("app_pages/dashboard.py", title="Dashboard", icon=":material/dashboard:"),
            st.Page("app_pages/sprint_planning.py", title="Sprint Planning", icon=":material/assignment:"),
            st.Page("app_pages/sprint_allocation.py", title="Sprint Allocation Board", icon=":material/view_kanban:"),
            st.Page("app_pages/team_capacity.py", title="Team Capacity", icon=":material/groups:"),
            st.Page("app_pages/presence_holidays.py", title="Presence & Holidays", icon=":material/calendar_today:"),
            st.Page("app_pages/team_system_setup.py", title="Team & System Setup", icon=":material/settings:"),
            st.Page("app_pages/sprint_reports.py", title="Sprint Reports", icon=":material/assessment:"),
        ])
    pg.run()

    # 3. Render Bottom of Sidebar: Profile, Change Password & Logout
    st.sidebar.markdown("<br><br><hr style='margin-top: 1rem; margin-bottom: 1rem;'>", unsafe_allow_html=True)
    st.sidebar.markdown("### User Profile")
    
    col_av, col_details = st.sidebar.columns([1, 3])
    with col_av:
        st.markdown("<h1 style='margin:0; text-align:center;'>👤</h1>", unsafe_allow_html=True)
    with col_details:
        st.markdown(f"**{st.session_state.user['name']}**")
        st.caption(f"{st.session_state.user['email']}")
        
    st.sidebar.caption(f"Role: **{st.session_state.user['user_role']}**")
    
    if st.session_state.user['team_id']:
        db = get_mongo_db()
        team_doc = db['teams'].find_one({"_id": ObjectId(st.session_state.user['team_id'])})
        if team_doc:
            st.sidebar.caption(f"Team: **{team_doc['name']}**")
            
    st.sidebar.markdown("---")
    
    # Change password foldout
    with st.sidebar.expander("🔑 Change Password"):
        with st.form("change_password_form", clear_on_submit=True):
            old_p = st.text_input("Old password", type="password")
            new_p = st.text_input("New password", type="password")
            conf_p = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Update password", use_container_width=True):
                if not old_p or not new_p or not conf_p:
                    st.error("Please fill in all password fields.")
                elif new_p != conf_p:
                    st.error("New passwords do not match.")
                else:
                    db = get_mongo_db()
                    user_doc = db['users'].find_one({"_id": ObjectId(st.session_state.user['id'])})
                    if user_doc and user_doc['password'] == hash_password(old_p):
                        success = change_user_password(st.session_state.user['id'], new_p)
                        if success:
                            st.success("Password updated successfully!")
                        else:
                            st.error("Failed to update password.")
                    else:
                        st.error("Incorrect old password.")
                    
    # Log out button
    if st.sidebar.button("Log out", type="secondary", use_container_width=True):
        st.session_state.user = None
        st.session_state.token = None
        
        # Clear local cookie, entire localStorage, and reload (via parent SVG script)
        st.markdown("""
            <svg style="display:none;"><script>
                document.cookie = 'sprint_cockpit_token=; path=/; max-age=0; SameSite=Lax';
                localStorage.clear();
                location.reload();
            </script></svg>
        """, unsafe_allow_html=True)
        st.stop()
