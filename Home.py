import streamlit as st

st.set_page_config(page_title="DBES Post-Evaluation System", page_icon="📋", layout="wide")

import db
import auth

# The public evaluation form must be reachable WITHOUT logging in, so it is
# excluded from the auth-gated navigation below and instead handled as its
# own always-available page.
evaluate_page = st.Page("pages/evaluate.py", title="Evaluate", url_path="Evaluate", icon="📝")

if not auth.is_logged_in():
    # Not logged in: only the public evaluation page + the login gate on Home are usable.
    db.init_db()
    query_token = st.query_params.get("token")
    if query_token:
        pg = st.navigation([evaluate_page], position="hidden")
        pg.run()
    else:
        auth.require_login()
    st.stop()

dashboard_page = st.Page("pages/dashboard.py", title="Dashboard", url_path="Dashboard", icon="📊", default=True)
create_activity_page = st.Page("pages/create_activity.py", title="Create Activity", url_path="Create-Activity", icon="➕")
activity_results_page = st.Page("pages/activity_results.py", title="Activity Results", url_path="Activity-Results", icon="📈")
manage_users_page = st.Page("pages/manage_users.py", title="Manage Users", url_path="Manage-Users", icon="👥")
my_account_page = st.Page("pages/my_account.py", title="My Account", url_path="My-Account", icon="⚙️")
audit_log_page = st.Page("pages/audit_log.py", title="Audit Log", url_path="Audit-Log", icon="🗂️")

pg = st.navigation(
    {
        "Evaluations": [dashboard_page, create_activity_page, activity_results_page],
        "Administration": [manage_users_page, my_account_page, audit_log_page],
        "Public form (for reference)": [evaluate_page],
    }
)

with st.sidebar:
    user = auth.current_user()
    st.markdown(f"**{user['full_name']}**")
    st.caption("HR Officer")
    if st.button("Log out", use_container_width=True):
        auth.logout()
        st.rerun()

pg.run()
