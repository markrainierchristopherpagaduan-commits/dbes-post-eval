import streamlit as st

import db
import utils

db.init_db()

token = st.query_params.get("token")

if not token:
    st.error("No activity specified. Please scan the QR code provided at the venue.")
    st.stop()

activity = db.get_activity_by_token(token)

if not activity:
    st.error("This evaluation link is invalid.")
    st.stop()

if activity["status"] != "open":
    st.warning("This evaluation is no longer accepting responses. Thank you for your interest.")
    st.stop()

st.title(activity["title"])
meta_bits = [b for b in [activity["activity_type"], activity["activity_date"], activity["venue"]] if b]
st.caption(" · ".join(meta_bits))

speakers = db.get_activity_speakers(activity["id"])
if speakers:
    speaker_bits = [f'Session {sp["session"]}: {sp["name"]}' + (f' ({sp["topic"]})' if sp["topic"] else "") for sp in speakers]
    st.caption("Speaker(s): " + " · ".join(speaker_bits))

st.write("Thank you for attending. Please take a moment to complete this post-evaluation.")

if st.session_state.get(f"submitted_{activity['id']}"):
    st.success("Your response has been recorded. Thank you!")
    st.stop()

questions = db.get_activity_questions(activity["id"])

with st.form("eval_form"):
    st.subheader("Your information")
    name = st.text_input("Name")
    school = st.text_input("School")

    st.divider()
    st.subheader("Evaluation")
    st.caption("Fields marked * are required.")

    answers = {}
    current_category = None
    for qn in questions:
        if qn["category"] != current_category:
            st.markdown(f"**{qn['category']}**")
            current_category = qn["category"]

        if qn["qtype"] == "rating":
            answers[qn["id"]] = st.slider(qn["question_text"], 1, 5, 3, help=utils.rating_scale_help(), key=f"q_{qn['id']}")
        elif qn["qtype"] == "multiple_choice":
            options = (qn["options"] or "").split("|") if qn["options"] else ["Yes", "No"]
            answers[qn["id"]] = st.radio(qn["question_text"], options, key=f"q_{qn['id']}")
        else:
            answers[qn["id"]] = st.text_area(f'{qn["question_text"]} *', key=f"q_{qn['id']}")

    submitted = st.form_submit_button("Submit evaluation", type="primary")

if submitted:
    missing = [
        qn["question_text"] for qn in questions
        if qn["qtype"] == "open_ended" and not (answers.get(qn["id"]) or "").strip()
    ]
    if missing:
        st.error(
            "Please answer all required open-ended questions before submitting:\n\n"
            + "\n".join(f"- {m}" for m in missing)
        )
    else:
        formatted = [{"question_id": qid, "qtype": next(q["qtype"] for q in questions if q["id"] == qid), "value": val}
                     for qid, val in answers.items()]
        db.submit_response(activity["id"], name.strip() or None, school.strip() or None, formatted)
        st.session_state[f"submitted_{activity['id']}"] = True
        st.rerun()