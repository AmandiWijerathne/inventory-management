import plotly.express as px
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from backend.inventory_service import list_inventory
from backend.product_service import list_categories
from backend.warehouse_service import list_warehouses
from frontend.ui import STATUS_COLORS, currency, page_header, show_db_error

page_header("Inventory", "Search and analyze stock by product, warehouse, availability, and replenishment status.", "📋")

try:
    categories = list_categories()
    warehouses = list_warehouses()
    cols = st.columns([1.25, 1, 1, 1])
    search = cols[0].text_input("Search product", placeholder="Name or SKU")
    category = cols[1].selectbox("Category", ["All categories", *categories])
    warehouse_labels = dict(zip(warehouses["warehouse_name"], warehouses["warehouse_id"]))
    warehouse_name = cols[2].selectbox("Warehouse", ["All warehouses", *warehouse_labels])
    statuses = ["All statuses", "In Stock", "Low Stock", "Out of Stock", "Overstock"]
    status = cols[3].selectbox("Status", statuses)
    sort_cols = st.columns([1, 1, 2])
    sort = sort_cols[0].selectbox(
        "Sort by", ["product_name", "warehouse_name", "quantity_on_hand",
                    "inventory_value_lkr", "reorder_level", "last_updated"],
        format_func=lambda value: value.replace("_", " ").title(),
    )
    ascending = sort_cols[1].selectbox("Direction", ["Ascending", "Descending"]) == "Ascending"
    inventory = list_inventory(
        search, "" if category == "All categories" else category,
        "" if warehouse_name == "All warehouses" else warehouse_labels[warehouse_name],
        "" if status == "All statuses" else status, sort, ascending,
    )
except (SQLAlchemyError, RuntimeError) as error:
    show_db_error(error)
    st.stop()

total_units = int(inventory["quantity_on_hand"].sum()) if not inventory.empty else 0
total_value = inventory["inventory_value_lkr"].sum() if not inventory.empty else 0
k1, k2, k3 = st.columns(3)
k1.metric("Product / warehouse records", f"{len(inventory):,}")
k2.metric("Quantity on hand", f"{total_units:,}")
k3.metric("Filtered inventory value", currency(total_value))

if inventory.empty:
    st.info("No inventory records match the selected filters.")
else:
    columns = ["sku", "product_name", "category", "warehouse_name", "quantity_on_hand",
               "available_quantity", "reserved_quantity", "reorder_level", "maximum_stock_level",
               "inventory_status", "unit_cost_lkr", "inventory_value_lkr", "last_updated"]
    display = inventory[columns].copy()
    display.columns = ["SKU", "Product", "Category", "Warehouse", "On hand", "Available",
                       "Reserved", "Reorder at", "Maximum", "Status", "Unit cost (LKR)",
                       "Value (LKR)", "Last updated"]
    def color_status(value: str) -> str:
        color = STATUS_COLORS.get(value, "#65748b")
        return f"background-color: {color}; color: white; font-weight: 600"
    styled = display.style.map(color_status, subset=["Status"]).format({
        "Unit cost (LKR)": lambda value: currency(value, 2),
        "Value (LKR)": lambda value: currency(value, 2),
    })
    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.subheader("Inventory valuation by category")
    chart = inventory.groupby("category", as_index=False)["inventory_value_lkr"].sum()
    fig = px.bar(chart.sort_values("inventory_value_lkr"), x="inventory_value_lkr",
                 y="category", orientation="h",
                 labels={"inventory_value_lkr": "Value (LKR)", "category": ""},
                 color_discrete_sequence=["#3478a8"])
    fig.update_layout(height=max(300, len(chart) * 35), margin=dict(l=8, r=8, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
