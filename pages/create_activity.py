import datetime as dt

import streamlit as st

import db
import auth
import utils

auth.require_login()
user = auth.current_user()

st.title("➕ Create Activity")
st.caption("Set up a program, activity, seminar, or training and generate its evaluation QR code.")

# ---------------------------------------------------------------------------
# Step 1 — Activity details
# ---------------------------------------------------------------------------

with st.form("activity_details"):
    st.subheader("1. Activity details")
    title = st.text_input("Title *")
    activity_type = st.selectbox("Type *", utils.ACTIVITY_TYPES)
    activity_date = st.date_input("Date", value=dt.date.today())
    venue = st.text_input("Venue")
    col1, col2 = st.columns(2)
    with col1:
        hosting_school = st.text_input("Hosting School (leave blank if diocese-wide)")
    with col2:
        participants = st.text_input("Participants of the Activity", placeholder="e.g. School Principals, Grade 7-10 Teachers")
    details_submitted = st.form_submit_button("Save details & continue to speakers")

if details_submitted:
    if not title:
        st.error("Title is required.")
    else:
        st.session_state["pending_activity"] = {
            "title": title,
            "activity_type": activity_type,
            "activity_date": activity_date,
            "venue": venue,
            "hosting_school": hosting_school.strip() or None,
            "participants": participants.strip() or None,
        }
        st.session_state.pop("questions_ready", None)
        st.success("Details saved. Add the speaker(s) below.")

# ---------------------------------------------------------------------------
# Step 2 — Speakers (one or more)
# ---------------------------------------------------------------------------

if "pending_activity" in st.session_state and not st.session_state.get("questions_ready"):
    st.divider()
    st.subheader("2. Speaker(s)")
    st.caption("Add every speaker/facilitator/resource person for this activity. Each one gets their own set of rating questions that participants answer individually.")

    if "draft_speakers" not in st.session_state:
        st.session_state["draft_speakers"] = []

    for i, sp in enumerate(st.session_state["draft_speakers"]):
        cols = st.columns([3, 3, 1])
        cols[0].text_input("Speaker name", value=sp["name"], key=f"sp_name_{i}", disabled=True)
        cols[1].text_input("Topic/session (optional)", value=sp.get("topic") or "", key=f"sp_topic_{i}", disabled=True)
        if cols[2].button("Remove", key=f"sp_remove_{i}"):
            st.session_state["draft_speakers"].pop(i)
            st.rerun()

    with st.form("add_speaker_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 3, 1])
        new_name = c1.text_input("Speaker name")
        new_topic = c2.text_input("Topic/session (optional)")
        add_speaker_clicked = c3.form_submit_button("Add speaker")
    if add_speaker_clicked and new_name.strip():
        st.session_state["draft_speakers"].append({"name": new_name.strip(), "topic": new_topic.strip() or None})
        st.rerun()

    st.caption(f"{len(st.session_state['draft_speakers'])} speaker(s) added.")

    if st.button("Continue to evaluation questions →", type="primary",
                 disabled=len(st.session_state["draft_speakers"]) == 0):
        base_questions = db.list_base_questions()
        draft = [{**bq, "source": "base", "include": True, "speaker_index": None, "uid": db.new_id()} for bq in base_questions]

        order = len(draft) + 1
        for s_idx, sp in enumerate(st.session_state["draft_speakers"]):
            for text_template, qtype, _offset in db.DEFAULT_SPEAKER_QUESTIONS:
                draft.append({
                    "id": None,
                    "question_text": text_template.format(speaker=sp["name"]),
                    "qtype": qtype,
                    "category": f'Speaker: {sp["name"]}',
                    "options": None,
                    "order_index": order,
                    "source": "speaker",
                    "include": True,
                    "speaker_index": s_idx,
                    "uid": db.new_id(),
                })
                order += 1

        st.session_state["draft_questions"] = draft
        st.session_state["questions_ready"] = True
        st.rerun()

    if not st.session_state["draft_speakers"]:
        st.info("Add at least one speaker to continue. Most trainings will have 2 or more — add each one separately.")

# ---------------------------------------------------------------------------
# Step 3 — Evaluation questions
# ---------------------------------------------------------------------------

if st.session_state.get("questions_ready"):
    st.divider()
    st.subheader("3. Evaluation questions")
    st.caption(
        "Base questions and each speaker's auto-generated questions are pre-filled below. "
        "Uncheck to exclude, edit text/category inline, use ↑/↓ to reorder, or add new questions for this activity. "
        "The order shown here is the order participants will see on the evaluation form."
    )

    if st.button("← Back to speakers"):
        st.session_state.pop("questions_ready", None)
        st.session_state.pop("draft_questions", None)
        st.rerun()

    swap_request = None
    updated = []
    current_category = None
    n_questions = len(st.session_state["draft_questions"])
    for i, dq in enumerate(st.session_state["draft_questions"]):
        if dq["category"] != current_category:
            st.markdown(f"**{dq['category']}**")
            current_category = dq["category"]
        cols = st.columns([0.3, 0.3, 0.5, 3, 1.3, 1.3])
        if cols[0].button("↑", key=f"up_{dq['uid']}", disabled=(i == 0), help="Move up"):
            swap_request = ("up", i)
        if cols[1].button("↓", key=f"down_{dq['uid']}", disabled=(i == n_questions - 1), help="Move down"):
            swap_request = ("down", i)
        include = cols[2].checkbox("Use", value=dq["include"], key=f"inc_{dq['uid']}")
        text = cols[3].text_input("Question", value=dq["question_text"], key=f"txt_{dq['uid']}", label_visibility="collapsed")
        category = cols[4].text_input("Category", value=dq["category"], key=f"cat_{dq['uid']}", label_visibility="collapsed")
        qtype = cols[5].selectbox("Type", ["rating", "multiple_choice", "open_ended"],
                                   index=["rating", "multiple_choice", "open_ended"].index(dq["qtype"]),
                                   key=f"typ_{dq['uid']}", label_visibility="collapsed")
        updated.append({**dq, "include": include, "question_text": text, "category": category, "qtype": qtype})
    st.session_state["draft_questions"] = updated

    if swap_request:
        action, idx = swap_request
        lst = st.session_state["draft_questions"]
        if action == "up" and idx > 0:
            lst[idx - 1], lst[idx] = lst[idx], lst[idx - 1]
        elif action == "down" and idx < len(lst) - 1:
            lst[idx + 1], lst[idx] = lst[idx], lst[idx + 1]
        st.rerun()

    st.markdown("**Add a custom question for this activity**")
    with st.form("add_question_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 1.3, 1.3, 1])
        new_text = c1.text_input("Question text")
        new_category = c2.text_input("Category", value="Custom")
        new_type = c3.selectbox("Type", ["rating", "multiple_choice", "open_ended"])
        add_clicked = c4.form_submit_button("Add")
    if add_clicked and new_text.strip():
        st.session_state["draft_questions"].append({
            "id": None, "question_text": new_text.strip(), "qtype": new_type,
            "category": new_category.strip() or "Custom", "options": None,
            "order_index": len(st.session_state["draft_questions"]) + 1,
            "source": "custom", "include": True, "speaker_index": None, "uid": db.new_id(),
        })
        st.rerun()

    st.divider()
    if st.button("✅ Generate activity & QR code", type="primary"):
        pa = st.session_state["pending_activity"]
        result = db.create_activity(
            pa["title"], pa["activity_type"], pa["activity_date"], pa["venue"], pa["hosting_school"], pa["participants"],
            created_by=user["id"],
        )

        created_speakers = db.add_activity_speakers(result["id"], st.session_state["draft_speakers"])

        final_questions = []
        for idx, dq in enumerate(q for q in st.session_state["draft_questions"] if q["include"]):
            speaker_id = None
            if dq.get("speaker_index") is not None:
                speaker_id = created_speakers[dq["speaker_index"]]["id"]
            final_questions.append({
                "question_text": dq["question_text"],
                "qtype": dq["qtype"],
                "category": dq["category"],
                "options": dq.get("options"),
                "order_index": idx + 1,
                "source": dq["source"],
                "speaker_id": speaker_id,
            })
        db.add_activity_questions(result["id"], final_questions)
        db.log_action(user["id"], user["username"], "activity_created",
                       f'{pa["title"]} ({len(created_speakers)} speaker(s))')

        st.success(f"Activity '{pa['title']}' created with {len(created_speakers)} speaker(s) and {len(final_questions)} question(s).")
        eval_url = utils.build_evaluation_url(result["qr_token"])
        st.image(utils.generate_qr_png_bytes(eval_url), width=260, caption="Scan to evaluate")
        st.code(eval_url, language=None)

        for key in ("pending_activity", "draft_speakers", "draft_questions", "questions_ready"):
            st.session_state.pop(key, None)
