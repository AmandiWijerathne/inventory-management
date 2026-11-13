from datetime import date
import plotly.express as px
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from backend.inventory_service import inventory_alerts
from backend.product_service import list_categories, list_products
from backend.report_service import (
    inventory_valuation,
    monthly_movement_report,
    movement_report,
    supplier_inventory,
    to_csv_bytes,
    to_excel_bytes,
)
from backend.warehouse_service import list_warehouses, warehouse_summary
from frontend.ui import currency, page_header, show_db_error

page_header("Reports & analytics", "Filter operational reports and export the underlying database results.", "📈")

try:
    categories = list_categories()
    warehouses = list_warehouses()
    products = list_products()
except (SQLAlchemyError, RuntimeError) as error:
    show_db_error(error)
    st.stop()

filters = st.columns([1.15, 1.15, 1, 1])
date_range = filters[0].date_input(
    "Report date range", value=(date(2026, 1, 1), date.today()), key="report_dates"
)
start_date, end_date = (date_range if isinstance(date_range, tuple) and len(date_range) == 2
                        else (None, None))
category_options = ["All categories", *categories]
category = filters[1].selectbox("Category", category_options)
warehouse_labels = dict(zip(warehouses["warehouse_name"], warehouses["warehouse_id"]))
warehouse_name = filters[2].selectbox("Warehouse", ["All warehouses", *warehouse_labels])
product_labels = dict(zip(products["product_name"], products["product_id"]))
product_name = filters[3].selectbox("Product", ["All products", *product_labels])

report_kind = st.selectbox(
    "Report",
    ["Inventory valuation", "Category-wise inventory", "Warehouse-wise inventory",
     "Stock movements", "Monthly receipts and issues", "Low-stock products",
     "Supplier-wise inventory"],
)
warehouse_id = "" if warehouse_name == "All warehouses" else warehouse_labels[warehouse_name]
product_id = "" if product_name == "All products" else product_labels[product_name]
category_filter = "" if category == "All categories" else category

try:
    if report_kind in {"Inventory valuation", "Category-wise inventory"}:
        data = inventory_valuation(
            start_date, end_date, category_filter, warehouse_id, product_id
        )
        if report_kind == "Category-wise inventory":
            data = (data.groupby("category", as_index=False)
                    .agg(product_locations=("inventory_id", "count"),
                         stock_units=("quantity_on_hand", "sum"),
                         inventory_value_lkr=("inventory_value_lkr", "sum")))
        else:
            data = data[["sku", "product_name", "category", "warehouse_name",
                         "quantity_on_hand", "reserved_quantity", "inventory_status",
                         "unit_cost_lkr", "inventory_value_lkr", "last_updated"]]
    elif report_kind == "Warehouse-wise inventory":
        data = warehouse_summary(
            category_filter, product_id, warehouse_id, start_date, end_date
        )
        data = data[["warehouse_name", "city", "province", "capacity_units", "stock_units",
                     "inventory_value_lkr", "capacity_utilization_pct"]]
    elif report_kind == "Stock movements":
        data = movement_report(product_id, warehouse_id, "", start_date, end_date, category_filter)
    elif report_kind == "Monthly receipts and issues":
        data = monthly_movement_report(
            start_date, end_date, warehouse_id, category_filter, product_id
        )
    elif report_kind == "Low-stock products":
        data = inventory_alerts(warehouse_id, start_date, end_date)
        data = data[data["inventory_status"].isin(["Low Stock", "Out of Stock"])]
        if category_filter:
            data = data[data["category"] == category_filter]
        if product_id:
            data = data[data["product_id"] == product_id]
    else:
        data = supplier_inventory(
            warehouse_id, category_filter, product_id, start_date, end_date
        )
    if report_kind == "Inventory valuation" and not data.empty:
        st.metric("Filtered inventory value", currency(data["inventory_value_lkr"].sum()))
    if report_kind in {"Inventory valuation", "Category-wise inventory",
                       "Warehouse-wise inventory", "Low-stock products",
                       "Supplier-wise inventory"}:
        st.caption("This report reflects current inventory, not historical stock snapshots; its date range filters inventory update dates only where available.")
    if report_kind == "Warehouse-wise inventory" and not data.empty:
        st.caption("Capacity utilization is total units on hand ÷ configured unit capacity, not physical volume.")
    if data.empty:
        st.info("No report rows match the selected filters.")
    else:
        st.dataframe(data, use_container_width=True, hide_index=True)
        if "inventory_value_lkr" in data.columns:
            plot_data = data
            group_column = "category" if "category" in data else (
                "warehouse_name" if "warehouse_name" in data else None
            )
            if group_column:
                chart = plot_data.groupby(group_column, as_index=False)["inventory_value_lkr"].sum()
                fig = px.bar(chart.sort_values("inventory_value_lkr"),
                             x="inventory_value_lkr", y=group_column, orientation="h",
                             labels={"inventory_value_lkr": "Value (LKR)", group_column: ""})
                fig.update_layout(height=max(300, len(chart) * 35))
                st.plotly_chart(fig, use_container_width=True)
        csv_name = f"{report_kind.lower().replace(' ', '_')}.csv"
        st.download_button("Download report as CSV", data=to_csv_bytes(data),
                           file_name=csv_name, mime="text/csv")
        excel_data = to_excel_bytes({report_kind[:31]: data})
        st.download_button("Download report as Excel", data=excel_data,
                           file_name=csv_name.removesuffix(".csv") + ".xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
except (SQLAlchemyError, RuntimeError) as error:
    show_db_error(error)
