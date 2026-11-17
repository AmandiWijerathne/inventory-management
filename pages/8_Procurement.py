from __future__ import annotations

import plotly.express as px
import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from backend.procurement_service import (
    PO_STATUS_TRANSITIONS,
    create_purchase_order,
    get_purchase_order_details,
    list_purchase_orders,
    procurement_recommendations,
    procurement_spend_dashboard,
    record_goods_receipt,
    supplier_performance_dashboard,
    update_purchase_order_status,
)
from backend.product_service import list_products, list_suppliers
from backend.warehouse_service import list_warehouses
from frontend.ui import currency, page_header, show_db_error

page_header(
    "Procurement management",
    "Monitor purchase orders, receiving activity, replenishment recommendations, and supplier performance.",
    "🛒",
)

try:
    suppliers = list_suppliers()
    products = list_products()
    warehouses = list_warehouses()
    purchase_orders = list_purchase_orders()
except (SQLAlchemyError, pd.errors.DatabaseError) as error:
    cause = error
    while cause is not None:
        original_error = getattr(cause, "orig", None)
        if (
            getattr(cause, "sqlstate", None) == "42P01"
            or getattr(original_error, "sqlstate", None) == "42P01"
        ):
            break
        cause = cause.__cause__
    if cause is not None:
        st.error(
            "The procurement tables are missing from the configured PostgreSQL database. "
            "Apply the latest schema from the project root, then reload this page."
        )
        st.code("python -m database.init_db --no-create-database", language="powershell")
        st.caption(
            "This creates missing tables and indexes without dropping or replacing existing data. "
            "Run it using the same DATABASE_URL as this application."
        )
        st.stop()
    if isinstance(error, SQLAlchemyError):
        show_db_error(error)
    else:
        st.error("The procurement database query failed. Check the PostgreSQL service and schema.")
    st.stop()
except RuntimeError as error:
    show_db_error(error)
    st.stop()

if purchase_orders.empty:
    st.info("No purchase orders exist yet. Create one from the form below.")
else:
    st.subheader("Purchase order overview")
    stats = st.columns(4)
    stats[0].metric("Open POs", int((purchase_orders['status'] != 'Received').sum()))
    stats[1].metric("Total value", currency(float(purchase_orders['total_amount_lkr'].sum())))
    stats[2].metric("Outstanding items", int(purchase_orders['outstanding_quantity'].sum()))
    stats[3].metric("Suppliers", purchase_orders['supplier_name'].nunique())
    st.dataframe(
        purchase_orders[["purchase_order_no", "supplier_name", "order_date", "status", "total_amount_lkr"]],
        use_container_width=True,
        hide_index=True,
    )
    status_po_no = st.selectbox(
        "Purchase order to update",
        purchase_orders["purchase_order_no"].tolist(),
        key="status_purchase_order_no",
    )
    status_po = purchase_orders.loc[
        purchase_orders["purchase_order_no"] == status_po_no
    ].iloc[0]
    allowed_statuses = sorted(PO_STATUS_TRANSITIONS.get(str(status_po["status"]), set()))
    if allowed_statuses:
        with st.form("update_purchase_order_status_form"):
            target_status = st.selectbox("New status", allowed_statuses)
            update_status = st.form_submit_button("Update purchase order status")
            if update_status:
                try:
                    update_purchase_order_status(
                        str(status_po["purchase_order_id"]), target_status
                    )
                    st.success(f"Purchase order status updated to {target_status}.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
                except SQLAlchemyError as error:
                    show_db_error(error)
    else:
        st.caption("This purchase order has no further status transitions.")

supplier_map = {row["supplier_name"]: row["supplier_id"] for _, row in suppliers.iterrows()}
product_map = {row["product_name"]: row["product_id"] for _, row in products.iterrows()}
warehouse_map = {row["warehouse_name"]: row["warehouse_id"] for _, row in warehouses.iterrows()}

purchase_tab, receiving_tab, planning_tab = st.tabs(["Create purchase order", "Goods receipt", "Procurement planning"])

with purchase_tab:
    if not suppliers.empty:
        with st.form("create_purchase_order_form", clear_on_submit=True):
            supplier_name = st.selectbox("Supplier", suppliers["supplier_name"].tolist())
            supplier_id = supplier_map[supplier_name]
            st.caption("Pick one or more products and prices for this purchase order.")
            selected_product = st.selectbox("Product", ["Select a product", *products["product_name"].tolist()])
            quantity = st.number_input("Quantity", min_value=1, step=1)
            unit_price = st.number_input("Unit price (LKR)", min_value=0.0, step=100.0)
            add_product = st.form_submit_button("Add to order")
            if add_product and selected_product != "Select a product":
                st.session_state.setdefault("po_items", [])
                st.session_state["po_items"].append({
                    "product_id": product_map[selected_product],
                    "quantity": int(quantity),
                    "unit_price_lkr": float(unit_price),
                })
                st.success(f"Added {selected_product} to the draft purchase order.")
            if st.session_state.get("po_items"):
                current_items = st.session_state["po_items"]
                item_table = []
                for entry in current_items:
                    product_name = products.loc[products["product_id"] == entry["product_id"], "product_name"].iloc[0]
                    item_table.append({
                        "Product": product_name,
                        "Quantity": entry["quantity"],
                        "Unit price (LKR)": entry["unit_price_lkr"],
                        "Line total (LKR)": entry["quantity"] * entry["unit_price_lkr"],
                    })
                st.dataframe(item_table, use_container_width=True, hide_index=True)
            order_date = st.date_input("Order date", value=None)
            expected_delivery_date = st.date_input("Expected delivery date")
            notes = st.text_area("Notes")
            submit_order = st.form_submit_button("Submit purchase order")
            if submit_order:
                if not st.session_state.get("po_items"):
                    st.error("Add at least one product before creating the purchase order.")
                else:
                    try:
                        po_number = create_purchase_order(
                            supplier_id=supplier_id,
                            items=st.session_state["po_items"],
                            order_date=order_date,
                            expected_delivery_date=expected_delivery_date,
                            notes=notes,
                        )
                    except ValueError as error:
                        st.error(str(error))
                    except SQLAlchemyError as error:
                        show_db_error(error)
                    else:
                        st.success(f"Purchase order created: {po_number}")
                        st.session_state["po_items"] = []
                        st.rerun()
    else:
        st.warning("Create a supplier before creating purchase orders.")

with receiving_tab:
    if purchase_orders.empty:
        st.info("There are no purchase orders to receive against yet.")
    else:
        purchase_order_no = st.selectbox(
            "Purchase order",
            purchase_orders["purchase_order_no"].tolist(),
        )
        warehouse_name = st.selectbox("Receiving warehouse", warehouses["warehouse_name"].tolist())
        selected_po = purchase_orders.loc[purchase_orders["purchase_order_no"] == purchase_order_no].iloc[0]
        if selected_po["status"] in {"Received", "Cancelled"}:
            st.warning("This purchase order is already fully received or cancelled.")
        elif selected_po["status"] not in {"Ordered", "Partially Received"}:
            st.info("Advance the purchase order to Ordered before recording a receipt.")
        else:
            po_items = get_purchase_order_details(
                purchase_order_id=str(selected_po["purchase_order_id"])
            )
            outstanding_items = po_items.loc[po_items["outstanding_quantity"] > 0]
            if outstanding_items.empty:
                st.info("There are no outstanding quantities on this purchase order.")
            else:
                receipt_product_map = dict(zip(
                    outstanding_items["product_name"], outstanding_items["product_id"]
                ))
                product_name = st.selectbox(
                    "Product to receive", list(receipt_product_map.keys())
                )
                po_item = outstanding_items.loc[
                    outstanding_items["product_name"] == product_name
                ].iloc[0]
                outstanding_quantity = int(po_item["outstanding_quantity"])
                qty = st.number_input(
                    "Quantity received", min_value=1, max_value=outstanding_quantity, step=1
                )
                unit_cost = st.number_input(
                    "Unit cost (LKR)", min_value=0.0,
                    value=float(po_item["unit_price_lkr"]), step=100.0,
                )
                if st.button("Record receipt"):
                    try:
                        receipt_no = record_goods_receipt(
                            purchase_order_id=str(selected_po["purchase_order_id"]),
                            warehouse_id=warehouse_map[warehouse_name],
                            received_items=[{
                                "product_id": receipt_product_map[product_name],
                                "quantity_received": int(qty),
                                "unit_cost_lkr": float(unit_cost),
                            }],
                        )
                    except ValueError as error:
                        st.error(str(error))
                    except SQLAlchemyError as error:
                        show_db_error(error)
                    else:
                        st.success(f"Goods receipt recorded: {receipt_no}")
                        st.rerun()

with planning_tab:
    recommendations = procurement_recommendations()
    if recommendations.empty:
        st.info("No replenishment actions required based on current thresholds and outstanding orders.")
    else:
        st.dataframe(
            recommendations[[
                "product_name",
                "warehouse_name",
                "quantity_on_hand",
                "reorder_level",
                "maximum_stock_level",
                "outstanding_po_quantity",
                "recommended_replenishment",
            ]],
            use_container_width=True,
            hide_index=True,
        )
    performance = supplier_performance_dashboard()
    if performance.empty:
        st.info("No procurement history is available for supplier performance analysis yet.")
    else:
        st.subheader("Supplier performance")
        st.dataframe(performance, use_container_width=True, hide_index=True)
    spend = procurement_spend_dashboard()
    if spend["monthly"].empty:
        st.info("No procurement spend is available for the selected period.")
    else:
        spend_chart = spend["monthly"].rename(columns={"order_month": "Month", "procurement_expenditure_lkr": "Total spend (LKR)"})
        fig = px.bar(spend_chart, x="Month", y="Total spend (LKR)", title="Monthly procurement spend")
        st.plotly_chart(fig, use_container_width=True)
