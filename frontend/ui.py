"""Shared visual styling, data formatting, and UI error handling."""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

STATUS_COLORS = {
    "In Stock": "#16a36a",
    "Low Stock": "#e89524",
    "Out of Stock": "#d84a4a",
    "Overstock": "#3478c8",
}


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #f5f7fb; color: #172338; }
        [data-testid="stSidebar"] { background: #101d32; }
        [data-testid="stSidebar"] * { color: #edf3fb !important; }
        .block-container { padding-top: 1.8rem; padding-bottom: 2rem; max-width: 1500px; }
        h1, h2, h3 { letter-spacing: -0.025em; color: #172338; }
        div[data-testid="stMetric"] {
            background: white; border: 1px solid #e6eaf1; padding: 17px 19px;
            border-radius: 12px; box-shadow: 0 2px 8px rgba(24, 42, 69, .04);
        }
        div[data-testid="stMetricLabel"] { color: #65748b; font-size: .88rem; }
        div[data-testid="stMetricValue"] { color: #172338; }
        div.stButton > button, div.stDownloadButton > button {
            border-radius: 8px; border: 1px solid #d6deea; font-weight: 600;
        }
        .page-kicker { color: #52729d; font-size: .82rem; font-weight: 700;
            letter-spacing: .1em; text-transform: uppercase; margin-bottom: .1rem; }
        .subtle { color: #65748b; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str, icon: str = "📦") -> None:
    st.markdown(f'<div class="page-kicker">SCM INVENTORY • OPERATIONS</div>', unsafe_allow_html=True)
    st.title(f"{icon}  {title}")
    st.caption(subtitle)


def currency(value: object, decimals: int = 0) -> str:
    try:
        return f"LKR {float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "LKR 0"


def format_currency_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    styled = frame.style
    valid = [column for column in columns if column in frame.columns]
    return styled.format({column: lambda value: currency(value, 2) for column in valid})


def show_db_error(error: SQLAlchemyError | RuntimeError) -> None:
    if isinstance(error, RuntimeError):
        logger.error("PostgreSQL configuration error: %s", error)
        st.error(str(error))
    else:
        logger.exception("PostgreSQL operation failed", exc_info=error)
        st.error("The PostgreSQL request failed. Check the database service, schema, and .env settings.")
