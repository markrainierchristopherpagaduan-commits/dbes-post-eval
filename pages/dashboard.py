import streamlit as st
import pandas as pd

import db
import auth
import utils

auth.require_login()

st.title("📊 Dashboard")

activities = db.list_activities()

if not activities:
    st.info("No activities yet. Go to **Create Activity** to set up your first evaluation.")
else:
    rows = []
    for a in activities:
        rows.append({
            "Title": a["title"],
            "Type": a["activity_type"],
            "Date": a["activity_date"],
            "School/Participants": a["hosting_school"] or a["participants"] or "—",
            "Status": a["status"],
            "Responses": db.count_responses(a["id"]),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Quick access")
    titles = {f'{a["title"]} — {a["activity_date"] or "no date"}': a for a in activities}
    choice = st.selectbox("Select an activity", list(titles.keys()))
    selected = titles[choice]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Responses collected", db.count_responses(selected["id"]))
    with col2:
        st.metric("Status", selected["status"])
    with col3:
        new_status = "closed" if selected["status"] == "open" else "open"
        if st.button(f"Mark as {new_status}"):
            db.set_activity_status(selected["id"], new_status)
            db.log_action(auth.current_user()["id"], auth.current_user()["username"], "activity_status_change",
                           f'{selected["title"]} -> {new_status}')
            st.rerun()

    speakers = db.get_activity_speakers(selected["id"])
    if speakers:
        st.caption("Speaker(s): " + " · ".join(sp["name"] for sp in speakers))

    st.image(utils.generate_qr_png_bytes(utils.build_evaluation_url(selected["qr_token"])), width=220,
              caption="Evaluation QR code")
    st.code(utils.build_evaluation_url(selected["qr_token"]), language=None)
    if st.button("Go to Activity Results →"):
        st.session_state["selected_activity_id"] = selected["id"]
        st.switch_page("pages/activity_results.py")
