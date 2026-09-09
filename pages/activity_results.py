import streamlit as st
import pandas as pd

import db
import auth
import report

auth.require_login()

st.title("📈 Activity Results")

activities = db.list_activities()
if not activities:
    st.info("No activities yet.")
    st.stop()

titles = {f'{a["title"]} — {a["activity_date"] or "no date"}': a for a in activities}
default_id = st.session_state.get("selected_activity_id")
default_label = next((k for k, v in titles.items() if v["id"] == default_id), list(titles.keys())[0])
choice = st.selectbox("Activity", list(titles.keys()), index=list(titles.keys()).index(default_label))
activity = titles[choice]

n_responses = db.count_responses(activity["id"])
st.metric("Total responses", n_responses)

if n_responses == 0:
    st.info("No responses yet for this activity.")
    st.stop()

st.subheader("Ratings summary")
rating_summary = db.get_rating_summary(activity["id"])
if rating_summary:
    df = pd.DataFrame(rating_summary)[["category", "question_text", "avg_rating", "n"]]
    df.columns = ["Category", "Question", "Average rating (1–5)", "# Responses"]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.caption("No rating-type questions on this activity.")

speakers = db.get_activity_speakers(activity["id"])
if speakers:
    st.subheader("Per-speaker ratings")
    speaker_avgs = db.get_speaker_rating_averages(activity["id"])
    sdf = pd.DataFrame(speaker_avgs)[["session", "name", "topic", "avg_rating", "n"]]
    sdf["session"] = sdf["session"].apply(lambda s: f"Session {s}" if s is not None else "—")
    sdf.columns = ["Session", "Speaker", "Topic", "Overall average rating (1–5)", "# Ratings"]
    st.dataframe(sdf, use_container_width=True, hide_index=True)

st.subheader("Open-ended responses")
open_answers = db.get_open_ended_answers(activity["id"])
if open_answers:
    categories = sorted(set(a["category"] for a in open_answers))
    for cat in categories:
        with st.expander(f"{cat} ({sum(1 for a in open_answers if a['category'] == cat)} responses)"):
            for a in open_answers:
                if a["category"] == cat:
                    st.write(f"- {a['answer_text']}")
else:
    st.caption("No open-ended responses yet.")

st.divider()
st.subheader("Qualitative summary")
st.caption("Write your own summary of the open-ended responses for each category below. This is what gets included in the Word report.")

existing_summaries = {s["category"]: s for s in db.get_ai_summaries(activity["id"])}

if open_answers:
    categories = sorted(set(a["category"] for a in open_answers))
    for cat in categories:
        current_text = existing_summaries.get(cat, {}).get("summary_text", "")
        with st.form(f"summary_form_{cat}"):
            st.markdown(f"**{cat}**")
            new_text = st.text_area(
                "Summary", value=current_text, key=f"summary_text_{cat}",
                label_visibility="collapsed", height=120,
                placeholder=f"Summarize the {cat.lower()} responses in your own words...",
            )
            save_clicked = st.form_submit_button("Save summary")
        if save_clicked:
            n_for_category = sum(1 for a in open_answers if a["category"] == cat)
            db.save_ai_summary(activity["id"], cat, new_text.strip(), n_for_category)
            st.success(f"Summary for '{cat}' saved.")
            st.rerun()
else:
    st.caption("No open-ended responses yet, so there's nothing to summarize.")

st.divider()
st.subheader("Report")
st.caption("Includes the quantitative summary, per-speaker breakdown, and your qualitative summary above.")
report_bytes = report.build_report(activity["id"])
st.download_button(
    "⬇️ Download Word report (.docx)",
    data=report_bytes,
    file_name=f'{activity["title"].strip().replace(" ", "_")}_Post_Evaluation_Report.docx',
    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
