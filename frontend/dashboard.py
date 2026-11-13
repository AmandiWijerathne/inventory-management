"""Executive dashboard composition."""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from backend.analytics_service import (
    category_value,
    dashboard_kpis,
    monthly_receipts_issues,
    status_distribution,
    top_products_by_value,
    warehouse_stock_distribution,
)
from backend.stock_movement_service import movement_history
from frontend.ui import STATUS_COLORS, currency, page_header, show_db_error


def render_dashboard() -> None:
    page_header(
        "Inventory overview",
        "A live view of stock, valuation, warehouse distribution, and recent movement activity.",
        "📊",
    )
    try:
        kpis = dashboard_kpis()
        category = category_value()
        warehouse = warehouse_stock_distribution()
        monthly = monthly_receipts_issues()
        statuses = status_distribution()
        top = top_products_by_value()
        recent = movement_history(limit=12)
    except (SQLAlchemyError, RuntimeError) as error:
        show_db_error(error)
        return

    metrics = st.columns(6)
    metrics[0].metric("Total products", f"{int(kpis['total_products']):,}")
    metrics[1].metric("Inventory quantity", f"{int(kpis['total_inventory_quantity']):,}")
    metrics[2].metric("Inventory value", currency(kpis["total_inventory_value_lkr"]))
    metrics[3].metric("Warehouses", f"{int(kpis['total_warehouses']):,}")
    metrics[4].metric("Low-stock locations", f"{int(kpis['low_stock_items']):,}")
    metrics[5].metric("Out of stock", f"{int(kpis['out_of_stock_items']):,}")

    first, second = st.columns([1.25, 1])
    with first:
        st.subheader("Inventory value by category")
        fig = px.bar(
            category.sort_values("inventory_value_lkr"),
            x="inventory_value_lkr", y="category", orientation="h",
            labels={"inventory_value_lkr": "Inventory value (LKR)", "category": ""},
            color="inventory_value_lkr", color_continuous_scale=["#b9d5f1", "#2468a8"],
        )
        fig.update_layout(height=390, coloraxis_showscale=False, margin=dict(l=8, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with second:
        st.subheader("Stock distribution by warehouse")
        fig = px.pie(
            warehouse, values="stock_units", names="warehouse_name", hole=.56,
            color_discrete_sequence=["#2468a8", "#3b83b9", "#63a6c8", "#8cc2d3", "#bedde1"],
            labels={"stock_units": "Units", "warehouse_name": "Warehouse"},
        )
        fig.update_layout(height=390, margin=dict(l=8, r=8, t=10, b=10), legend_title="")
        st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Monthly receipts vs. issues")
        fig = go.Figure()
        fig.add_bar(x=monthly["month"], y=monthly["receipts"], name="Receipts", marker_color="#178f78")
        fig.add_bar(x=monthly["month"], y=monthly["issues"], name="Issues", marker_color="#df765b")
        fig.update_layout(
            barmode="group", height=330, margin=dict(l=8, r=8, t=10, b=10),
            xaxis_title="", yaxis_title="Units", legend_title="",
        )
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Inventory status")
        fig = px.pie(
            statuses, values="item_locations", names="inventory_status", hole=.56,
            color="inventory_status", color_discrete_map=STATUS_COLORS,
            labels={"item_locations": "Product / warehouse locations", "inventory_status": "Status"},
        )
        fig.update_layout(height=330, margin=dict(l=8, r=8, t=10, b=10), legend_title="")
        st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Top 10 products by inventory value")
        fig = px.bar(
            top.sort_values("inventory_value_lkr"), x="inventory_value_lkr",
            y="product_name", orientation="h", hover_data=["sku"],
            labels={"inventory_value_lkr": "Value (LKR)", "product_name": ""},
            color_discrete_sequence=["#3576ac"],
        )
        fig.update_layout(height=390, margin=dict(l=8, r=8, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Recent stock movements")
        if recent.empty:
            st.info("No stock movements are available.")
        else:
            display = recent[["movement_date", "product_name", "warehouse_name",
                              "movement_type", "quantity", "reference_no"]].copy()
            display.columns = ["Date", "Product", "Warehouse", "Type", "Qty", "Reference"]
            st.dataframe(display, use_container_width=True, hide_index=True, height=390)
