"""
db.py — Turso (libSQL) data layer for the DBES Post-Evaluation System.

Uses the pure-Python `libsql-client` package (HTTP/WebSocket transport,
no Rust compiler needed) — same approach used for the DBES HR Forms
Dashboard on Windows.
"""

from __future__ import annotations

import os
import uuid
import datetime as dt
from typing import Any, Optional

import streamlit as st
import libsql_client

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_secret(name: str) -> str:
    if name in st.secrets:
        return st.secrets[name]
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required secret/env var '{name}'. "
            "Set it in .streamlit/secrets.toml (local) or App Settings -> Secrets (Streamlit Cloud)."
        )
    return val


@st.cache_resource(show_spinner=False)
def get_client() -> "libsql_client.Client":
    url = _get_secret("TURSO_DATABASE_URL")
    token = _get_secret("TURSO_AUTH_TOKEN")
    return libsql_client.create_client_sync(url=url, auth_token=token)


def q(sql: str, params: Optional[list | dict] = None):
    """Run a query and return the ResultSet."""
    client = get_client()
    return client.execute(sql, params or [])


def qmany(statements: list[tuple[str, list]]):
    """Run several statements in a single batch (best-effort transaction)."""
    client = get_client()
    return client.batch([(sql, params) for sql, params in statements])


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin')),
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        activity_date TEXT,
        venue TEXT,
        hosting_school TEXT,
        participants TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        qr_token TEXT UNIQUE NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS base_questions (
        id TEXT PRIMARY KEY,
        question_text TEXT NOT NULL,
        qtype TEXT NOT NULL CHECK (qtype IN ('rating', 'multiple_choice', 'open_ended')),
        category TEXT NOT NULL,
        options TEXT,
        order_index INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activity_speakers (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL REFERENCES activities(id),
        name TEXT NOT NULL,
        topic TEXT,
        session_number INTEGER,
        order_index INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activity_questions (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL REFERENCES activities(id),
        question_text TEXT NOT NULL,
        qtype TEXT NOT NULL CHECK (qtype IN ('rating', 'multiple_choice', 'open_ended')),
        category TEXT NOT NULL,
        options TEXT,
        order_index INTEGER NOT NULL,
        source TEXT NOT NULL DEFAULT 'base',
        speaker_id TEXT REFERENCES activity_speakers(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS responses (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL REFERENCES activities(id),
        participant_name TEXT,
        participant_school TEXT,
        submitted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS response_answers (
        id TEXT PRIMARY KEY,
        response_id TEXT NOT NULL REFERENCES responses(id),
        question_id TEXT NOT NULL REFERENCES activity_questions(id),
        answer_rating INTEGER,
        answer_choice TEXT,
        answer_text TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_summaries (
        id TEXT PRIMARY KEY,
        activity_id TEXT NOT NULL REFERENCES activities(id),
        category TEXT NOT NULL,
        summary_text TEXT NOT NULL,
        response_count INTEGER NOT NULL,
        generated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        username TEXT,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL
    )
    """,
]

DEFAULT_BASE_QUESTIONS = [
    # (text, qtype, category, options, order)
    ("The objectives of this activity were clearly explained.", "rating", "Content & Objectives", None, 1),
    ("The content was relevant and useful to my work.", "rating", "Content & Objectives", None, 2),
    ("The facilitator(s)/resource speaker(s) were knowledgeable.", "rating", "Facilitator", None, 3),
    ("The facilitator(s) delivered the session in an engaging way.", "rating", "Facilitator", None, 4),
    ("The venue and facilities were adequate.", "rating", "Logistics & Venue", None, 5),
    ("The schedule/time allotment was sufficient.", "rating", "Logistics & Venue", None, 6),
    ("Overall, how would you rate this activity?", "rating", "Overall", None, 7),
    ("What were the strengths of this activity?", "open_ended", "Strengths", None, 8),
    ("What areas need improvement?", "open_ended", "Areas to Improve", None, 9),
    ("Any other suggestions or comments?", "open_ended", "Suggestions", None, 10),
]


DEFAULT_SPEAKER_QUESTIONS = [
    # (text_template, qtype, order_offset) — {speaker} is replaced with the speaker's name
    ("{speaker} was knowledgeable about the topic.", "rating", 1),
    ("{speaker} delivered the session in a clear and engaging manner.", "rating", 2),
    ("{speaker} answered questions/clarifications well.", "rating", 3),
]


def _try(sql: str):
    """Run a migration statement, ignoring errors (e.g. column already renamed/exists)."""
    try:
        q(sql)
    except Exception:
        pass


def init_db():
    """Create tables if missing, migrate older column names, and seed default base questions once."""
    qmany([(s, []) for s in SCHEMA_STATEMENTS])

    # Migrate activities created before the "hosting_school"/"participants" rename
    # (previously "school"/"vicariate"). Safe to run every time — no-ops once done.
    _try("ALTER TABLE activities RENAME COLUMN school TO hosting_school")
    _try("ALTER TABLE activities RENAME COLUMN vicariate TO participants")
    _try("ALTER TABLE activities ADD COLUMN hosting_school TEXT")
    _try("ALTER TABLE activities ADD COLUMN participants TEXT")
    _try("ALTER TABLE activity_speakers ADD COLUMN session_number INTEGER")

    existing = q("SELECT COUNT(*) AS c FROM base_questions")
    count = existing.rows[0][0] if existing.rows else 0
    if count == 0:
        for text, qtype, category, options, order in DEFAULT_BASE_QUESTIONS:
            q(
                "INSERT INTO base_questions (id, question_text, qtype, category, options, order_index) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [new_id(), text, qtype, category, options, order],
            )


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------

def get_user_by_username(username: str) -> Optional[dict]:
    rs = q("SELECT id, username, password_hash, full_name, role, is_active FROM users WHERE username = ?", [username])
    if not rs.rows:
        return None
    r = rs.rows[0]
    return {"id": r[0], "username": r[1], "password_hash": r[2], "full_name": r[3], "role": r[4], "is_active": r[5]}


def create_user(username: str, password_hash: str, full_name: str, role: str = "admin"):
    q(
        "INSERT INTO users (id, username, password_hash, full_name, role, is_active, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        [new_id(), username, password_hash, full_name, role, now()],
    )


def any_users_exist() -> bool:
    rs = q("SELECT COUNT(*) FROM users")
    return (rs.rows[0][0] if rs.rows else 0) > 0


def list_users() -> list[dict]:
    rs = q("SELECT id, username, full_name, role, is_active, created_at FROM users ORDER BY created_at")
    return [
        {"id": r[0], "username": r[1], "full_name": r[2], "role": r[3], "is_active": r[4], "created_at": r[5]}
        for r in rs.rows
    ]


def set_user_active(user_id: str, active: bool):
    q("UPDATE users SET is_active = ? WHERE id = ?", [1 if active else 0, user_id])


def update_password(user_id: str, password_hash: str):
    q("UPDATE users SET password_hash = ? WHERE id = ?", [password_hash, user_id])


# ---------------------------------------------------------------------------
# Base questions
# ---------------------------------------------------------------------------

def list_base_questions(active_only: bool = True) -> list[dict]:
    sql = "SELECT id, question_text, qtype, category, options, order_index, is_active FROM base_questions"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY order_index"
    rs = q(sql)
    return [
        {"id": r[0], "question_text": r[1], "qtype": r[2], "category": r[3], "options": r[4], "order_index": r[5], "is_active": r[6]}
        for r in rs.rows
    ]


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

def create_activity(title, activity_type, activity_date, venue, hosting_school, participants, created_by) -> dict:
    activity_id = new_id()
    qr_token = uuid.uuid4().hex
    q(
        "INSERT INTO activities (id, title, activity_type, activity_date, venue, hosting_school, participants, "
        "status, qr_token, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
        [activity_id, title, activity_type, str(activity_date), venue, hosting_school, participants, qr_token, created_by, now()],
    )
    return {"id": activity_id, "qr_token": qr_token}


def add_activity_speakers(activity_id: str, speakers: list[dict]) -> list[dict]:
    """speakers: list of dicts with name, topic, session. Returns list with generated ids, in order."""
    stmts = []
    created = []
    for idx, sp in enumerate(speakers):
        sid = new_id()
        created.append({"id": sid, "name": sp["name"], "topic": sp.get("topic"), "session": sp.get("session")})
        stmts.append((
            "INSERT INTO activity_speakers (id, activity_id, name, topic, session_number, order_index) VALUES (?, ?, ?, ?, ?, ?)",
            [sid, activity_id, sp["name"], sp.get("topic"), sp.get("session"), idx + 1],
        ))
    if stmts:
        qmany(stmts)
    return created


def get_activity_speakers(activity_id: str) -> list[dict]:
    rs = q(
        "SELECT id, name, topic, session_number, order_index FROM activity_speakers WHERE activity_id = ? ORDER BY order_index",
        [activity_id],
    )
    return [{"id": r[0], "name": r[1], "topic": r[2], "session": r[3], "order_index": r[4]} for r in rs.rows]


def add_activity_questions(activity_id: str, questions: list[dict]):
    """questions: list of dicts with question_text, qtype, category, options, order_index, source, speaker_id (optional)"""
    stmts = []
    for qd in questions:
        stmts.append((
            "INSERT INTO activity_questions (id, activity_id, question_text, qtype, category, options, order_index, source, speaker_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [new_id(), activity_id, qd["question_text"], qd["qtype"], qd["category"], qd.get("options"),
             qd["order_index"], qd.get("source", "base"), qd.get("speaker_id")],
        ))
    if stmts:
        qmany(stmts)


def list_activities(status: Optional[str] = None) -> list[dict]:
    sql = "SELECT id, title, activity_type, activity_date, venue, hosting_school, participants, status, qr_token, created_at FROM activities"
    params = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    rs = q(sql, params)
    return [
        {"id": r[0], "title": r[1], "activity_type": r[2], "activity_date": r[3], "venue": r[4],
         "hosting_school": r[5], "participants": r[6], "status": r[7], "qr_token": r[8], "created_at": r[9]}
        for r in rs.rows
    ]


def get_activity(activity_id: str) -> Optional[dict]:
    rs = q(
        "SELECT id, title, activity_type, activity_date, venue, hosting_school, participants, status, qr_token, created_by, created_at "
        "FROM activities WHERE id = ?",
        [activity_id],
    )
    if not rs.rows:
        return None
    r = rs.rows[0]
    return {"id": r[0], "title": r[1], "activity_type": r[2], "activity_date": r[3], "venue": r[4],
            "hosting_school": r[5], "participants": r[6], "status": r[7], "qr_token": r[8], "created_by": r[9], "created_at": r[10]}


def get_activity_by_token(qr_token: str) -> Optional[dict]:
    rs = q(
        "SELECT id, title, activity_type, activity_date, venue, hosting_school, participants, status, qr_token "
        "FROM activities WHERE qr_token = ?",
        [qr_token],
    )
    if not rs.rows:
        return None
    r = rs.rows[0]
    return {"id": r[0], "title": r[1], "activity_type": r[2], "activity_date": r[3], "venue": r[4],
            "hosting_school": r[5], "participants": r[6], "status": r[7], "qr_token": r[8]}


def set_activity_status(activity_id: str, status: str):
    q("UPDATE activities SET status = ? WHERE id = ?", [status, activity_id])


def get_activity_questions(activity_id: str) -> list[dict]:
    rs = q(
        "SELECT id, question_text, qtype, category, options, order_index, speaker_id FROM activity_questions "
        "WHERE activity_id = ? ORDER BY order_index",
        [activity_id],
    )
    return [
        {"id": r[0], "question_text": r[1], "qtype": r[2], "category": r[3], "options": r[4], "order_index": r[5], "speaker_id": r[6]}
        for r in rs.rows
    ]


def get_speaker_rating_averages(activity_id: str) -> list[dict]:
    """One row per speaker: overall average across all of that speaker's rating questions."""
    rs = q(
        """
        SELECT sp.id, sp.name, sp.topic, sp.session_number, AVG(ra.answer_rating) AS avg_rating, COUNT(ra.answer_rating) AS n
        FROM activity_speakers sp
        LEFT JOIN activity_questions aq ON aq.speaker_id = sp.id AND aq.qtype = 'rating'
        LEFT JOIN response_answers ra ON ra.question_id = aq.id AND ra.answer_rating IS NOT NULL
        WHERE sp.activity_id = ?
        GROUP BY sp.id
        ORDER BY sp.order_index
        """,
        [activity_id],
    )
    return [{"id": r[0], "name": r[1], "topic": r[2], "session": r[3], "avg_rating": r[4], "n": r[5]} for r in rs.rows]


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

def submit_response(activity_id: str, participant_name: str, participant_school: str, answers: list[dict]) -> str:
    """answers: list of dicts with question_id, qtype, value"""
    response_id = new_id()
    stmts = [(
        "INSERT INTO responses (id, activity_id, participant_name, participant_school, submitted_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [response_id, activity_id, participant_name, participant_school, now()],
    )]
    for a in answers:
        rating = a["value"] if a["qtype"] == "rating" else None
        choice = a["value"] if a["qtype"] == "multiple_choice" else None
        text = a["value"] if a["qtype"] == "open_ended" else None
        stmts.append((
            "INSERT INTO response_answers (id, response_id, question_id, answer_rating, answer_choice, answer_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [new_id(), response_id, a["question_id"], rating, choice, text],
        ))
    qmany(stmts)
    return response_id


def count_responses(activity_id: str) -> int:
    rs = q("SELECT COUNT(*) FROM responses WHERE activity_id = ?", [activity_id])
    return rs.rows[0][0] if rs.rows else 0


def get_rating_summary(activity_id: str) -> list[dict]:
    """Average rating per rating-type question for this activity, including which speaker (if any) it's about."""
    rs = q(
        """
        SELECT aq.id, aq.question_text, aq.category, AVG(ra.answer_rating) AS avg_rating, COUNT(ra.answer_rating) AS n,
               sp.name AS speaker_name
        FROM activity_questions aq
        LEFT JOIN response_answers ra ON ra.question_id = aq.id AND ra.answer_rating IS NOT NULL
        LEFT JOIN activity_speakers sp ON sp.id = aq.speaker_id
        WHERE aq.activity_id = ? AND aq.qtype = 'rating'
        GROUP BY aq.id
        ORDER BY aq.order_index
        """,
        [activity_id],
    )
    return [
        {"question_id": r[0], "question_text": r[1], "category": r[2], "avg_rating": r[3], "n": r[4], "speaker_name": r[5]}
        for r in rs.rows
    ]


def get_open_ended_answers(activity_id: str, category: Optional[str] = None) -> list[dict]:
    sql = (
        "SELECT aq.category, aq.question_text, ra.answer_text FROM response_answers ra "
        "JOIN activity_questions aq ON aq.id = ra.question_id "
        "WHERE aq.activity_id = ? AND aq.qtype = 'open_ended' AND ra.answer_text IS NOT NULL AND ra.answer_text != ''"
    )
    params = [activity_id]
    if category:
        sql += " AND aq.category = ?"
        params.append(category)
    rs = q(sql, params)
    return [{"category": r[0], "question_text": r[1], "answer_text": r[2]} for r in rs.rows]


# ---------------------------------------------------------------------------
# Category summaries (written manually by the HR Officer, one per open-ended
# category; stored in the ai_summaries table/columns for schema continuity)
# ---------------------------------------------------------------------------

def save_ai_summary(activity_id: str, category: str, summary_text: str, response_count: int):
    q("DELETE FROM ai_summaries WHERE activity_id = ? AND category = ?", [activity_id, category])
    q(
        "INSERT INTO ai_summaries (id, activity_id, category, summary_text, response_count, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [new_id(), activity_id, category, summary_text, response_count, now()],
    )


def get_ai_summaries(activity_id: str) -> list[dict]:
    rs = q(
        "SELECT category, summary_text, response_count, generated_at FROM ai_summaries WHERE activity_id = ? ORDER BY category",
        [activity_id],
    )
    return [{"category": r[0], "summary_text": r[1], "response_count": r[2], "generated_at": r[3]} for r in rs.rows]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def log_action(user_id: Optional[str], username: Optional[str], action: str, details: str = ""):
    q(
        "INSERT INTO audit_log (id, user_id, username, action, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [new_id(), user_id, username, action, details, now()],
    )


def list_audit_log(limit: int = 200) -> list[dict]:
    rs = q("SELECT username, action, details, created_at FROM audit_log ORDER BY created_at DESC LIMIT ?", [limit])
    return [{"username": r[0], "action": r[1], "details": r[2], "created_at": r[3]} for r in rs.rows]
