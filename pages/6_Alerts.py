import plotly.express as px
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from backend.inventory_service import inventory_alerts, replenishment_recommendations
from backend.warehouse_service import list_warehouses
from frontend.ui import STATUS_COLORS, currency, page_header, show_db_error

page_header("Inventory alerts", "Prioritize stockouts and replenishment using each warehouse's current thresholds.", "🔔")
st.info("Replenishment recommendation = maximum stock level − current quantity on hand (floored at zero).")

try:
    warehouses = list_warehouses()
    warehouse_names = dict(zip(warehouses["warehouse_name"], warehouses["warehouse_id"]))
    selected_name = st.selectbox("Warehouse", ["All warehouses", *warehouse_names])
    selected_id = "" if selected_name == "All warehouses" else warehouse_names[selected_name]
    alerts = inventory_alerts(selected_id)
    recommendations = replenishment_recommendations(selected_id)
except (SQLAlchemyError, RuntimeError) as error:
    show_db_error(error)
    st.stop()

out = int((alerts["inventory_status"] == "Out of Stock").sum()) if not alerts.empty else 0
low = int((alerts["inventory_status"] == "Low Stock").sum()) if not alerts.empty else 0
over = int((alerts["inventory_status"] == "Overstock").sum()) if not alerts.empty else 0
columns = st.columns(4)
columns[0].metric("Out of stock", out)
columns[1].metric("Low stock", low)
columns[2].metric("Overstock", over)
columns[3].metric("Replenishment actions", len(recommendations))

if alerts.empty:
    st.success("No inventory alerts for the selected warehouse.")
else:
    chart = alerts.groupby("inventory_status", as_index=False).size()
    fig = px.pie(chart, names="inventory_status", values="size", hole=.5,
                 color="inventory_status", color_discrete_map=STATUS_COLORS)
    fig.update_layout(height=280, margin=dict(l=8, r=8, t=10, b=10), legend_title="")
    st.plotly_chart(fig, use_container_width=True)
    st.subheader("Warehouse-specific alerts")
    st.dataframe(alerts[["sku", "product_name", "category", "warehouse_name",
                         "quantity_on_hand", "available_quantity", "reserved_quantity",
                         "reorder_level", "maximum_stock_level", "inventory_status",
                         "inventory_value_lkr"]],
                 use_container_width=True, hide_index=True)

st.subheader("Products requiring replenishment")
if recommendations.empty:
    st.success("No replenishment recommendations at this time.")
else:
    display = recommendations[["sku", "product_name", "warehouse_name",
                               "quantity_on_hand", "reorder_level", "maximum_stock_level",
                               "recommended_replenishment", "inventory_status"]].copy()
    display.columns = ["SKU", "Product", "Warehouse", "On hand", "Reorder at",
                       "Target maximum", "Recommended quantity", "Status"]
    st.dataframe(display, use_container_width=True, hide_index=True)
