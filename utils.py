from __future__ import annotations

import io
import os

import qrcode
import streamlit as st


ACTIVITY_TYPES = ["Program", "Activity", "Seminar", "Seminar-Workshop", "Training"]


def get_app_base_url() -> str:
    if "APP_BASE_URL" in st.secrets:
        return str(st.secrets["APP_BASE_URL"]).rstrip("/")
    return os.environ.get("APP_BASE_URL", "http://localhost:8501").rstrip("/")


def build_evaluation_url(qr_token: str) -> str:
    base = get_app_base_url()
    return f"{base}/Evaluate?token={qr_token}"


def generate_qr_png_bytes(data: str) -> bytes:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def rating_scale_help() -> str:
    return "1 = Poor, 2 = Fair, 3 = Good, 4 = Very Good, 5 = Excellent"
