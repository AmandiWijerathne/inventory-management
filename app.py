"""Streamlit entry point and application navigation."""

from __future__ import annotations

import streamlit as st

from frontend.ui import apply_styles

st.set_page_config(
    page_title="SCM Inventory Management",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_styles()

navigation = st.navigation(
    [
        st.Page("pages/1_Dashboard.py", title="Dashboard overview", icon="📊", default=True),
        st.Page("pages/2_Products.py", title="Products", icon="📦"),
        st.Page("pages/3_Warehouses.py", title="Warehouses", icon="🏭"),
        st.Page("pages/4_Inventory.py", title="Inventory", icon="📋"),
        st.Page("pages/5_Stock_Movements.py", title="Stock movements", icon="🔄"),
        st.Page("pages/6_Alerts.py", title="Inventory alerts", icon="🔔"),
        st.Page("pages/7_Reports.py", title="Reports & analytics", icon="📈"),
    ]
)
navigation.run()
