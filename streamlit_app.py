from __future__ import annotations

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from CRAWLER.dashboard import render_crawler_dashboard

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

st.set_page_config(page_title="Tiki Auto Crawler", page_icon="🔎", layout="wide")

st.title("Tiki Auto Crawler & Preprocessing")
st.sidebar.info("Project hiện tập trung vào 2 phần: CRAWLER và PREPROCESSING.")

render_crawler_dashboard()
