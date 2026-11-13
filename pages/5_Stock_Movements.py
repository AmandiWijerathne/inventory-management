import logging
from datetime import date

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from backend.product_service import list_products
from backend.stock_movement_service import movement_history, record_movement, transfer_stock
from backend.warehouse_service import list_warehouses
from frontend.ui import page_header, show_db_error

logger = logging.getLogger(__name__)
page_header("Stock movements", "Record receipts, issues, adjustments, and atomic inter-warehouse transfers.", "🔄")

try:
    products = list_products()
    warehouses = list_warehouses()
except (SQLAlchemyError, RuntimeError) as error:
    show_db_error(error)
    st.stop()

if products.empty or warehouses.empty:
    st.warning("At least one product and one warehouse are required before recording stock.")
else:
    product_labels = dict(zip(
        products["product_id"],
        products["sku"] + " — " + products["product_name"],
    ))
    warehouse_labels = dict(zip(
        warehouses["warehouse_id"],
        warehouses["warehouse_name"] + " · " + warehouses["city"],
    ))
    receipt_tab, issue_tab, transfer_tab, adjustment_tab = st.tabs(
        ["Receive stock", "Issue stock", "Transfer stock", "Adjust stock"]
    )

    def submit_simple_movement(kind: str, product_id: str, warehouse_id: str,
                               quantity: int, notes: str, movement_date: date) -> None:
        try:
            reference = record_movement(
                product_id, warehouse_id, kind, quantity, notes, movement_date
            )
            st.success(f"{kind.replace('_', ' ').title()} recorded. Reference: {reference}")
            st.rerun()
        except ValueError as error:
            st.error(str(error))
        except (SQLAlchemyError, RuntimeError) as error:
            show_db_error(error)

    with receipt_tab:
        st.caption("Incoming stock increases available and on-hand quantity.")
        with st.form("receipt_form"):
            cols = st.columns(4)
            product_id = cols[0].selectbox("Product", list(product_labels),
                                            format_func=lambda value: product_labels[value],
                                            key="receipt_product")
            warehouse_id = cols[1].selectbox("Destination warehouse", list(warehouse_labels),
                                              format_func=lambda value: warehouse_labels[value],
                                              key="receipt_warehouse")
            quantity = cols[2].number_input("Quantity", min_value=1, value=1, step=1,
                                             key="receipt_quantity")
            movement_date = cols[3].date_input("Receipt date", value=date.today(),
                                                key="receipt_date")
            notes = st.text_input("Notes / supplier reference", key="receipt_notes")
            submitted = st.form_submit_button("Record receipt", type="primary")
        if submitted:
            submit_simple_movement("RECEIPT", product_id, warehouse_id, quantity, notes, movement_date)

    with issue_tab:
        st.caption("Issues are validated against available stock; reserved units are not issued.")
        with st.form("issue_form"):
            cols = st.columns(4)
            product_id = cols[0].selectbox("Product", list(product_labels),
                                            format_func=lambda value: product_labels[value],
                                            key="issue_product")
            warehouse_id = cols[1].selectbox("Source warehouse", list(warehouse_labels),
                                              format_func=lambda value: warehouse_labels[value],
                                              key="issue_warehouse")
            quantity = cols[2].number_input("Quantity", min_value=1, value=1, step=1,
                                             key="issue_quantity")
            movement_date = cols[3].date_input("Issue date", value=date.today(),
                                                key="issue_date")
            notes = st.text_input("Notes / issue reason", key="issue_notes")
            submitted = st.form_submit_button("Record issue", type="primary")
        if submitted:
            submit_simple_movement("ISSUE", product_id, warehouse_id, quantity, notes, movement_date)

    with transfer_tab:
        st.caption("Transfers create paired TRANSFER_OUT and TRANSFER_IN entries under one reference.")
        with st.form("transfer_form"):
            cols = st.columns(4)
            product_id = cols[0].selectbox("Product", list(product_labels),
                                            format_func=lambda value: product_labels[value],
                                            key="transfer_product")
            source_id = cols[1].selectbox("Source warehouse", list(warehouse_labels),
                                           format_func=lambda value: warehouse_labels[value],
                                           key="transfer_source")
            destination_id = cols[2].selectbox("Destination warehouse", list(warehouse_labels),
                                                format_func=lambda value: warehouse_labels[value],
                                                key="transfer_destination")
            quantity = cols[3].number_input("Quantity", min_value=1, value=1, step=1,
                                             key="transfer_quantity")
            movement_date = st.date_input("Transfer date", value=date.today(), key="transfer_date")
            notes = st.text_input("Notes / transfer reason", key="transfer_notes")
            submitted = st.form_submit_button("Transfer stock", type="primary")
        if submitted:
            try:
                reference = transfer_stock(
                    product_id, source_id, destination_id, quantity, notes, movement_date
                )
                st.success(f"Transfer completed atomically. Shared reference: {reference}")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
            except (SQLAlchemyError, RuntimeError) as error:
                show_db_error(error)

    with adjustment_tab:
        st.caption("Choose an adjustment direction. Decreases cannot consume reserved stock.")
        with st.form("adjustment_form"):
            cols = st.columns(4)
            direction = cols[0].selectbox(
                "Adjustment type", ["ADJUSTMENT_IN", "ADJUSTMENT_OUT"],
                format_func=lambda value: value.replace("_", " ").title(),
            )
            product_id = cols[1].selectbox("Product", list(product_labels),
                                            format_func=lambda value: product_labels[value],
                                            key="adjust_product")
            warehouse_id = cols[2].selectbox("Warehouse", list(warehouse_labels),
                                              format_func=lambda value: warehouse_labels[value],
                                              key="adjust_warehouse")
            quantity = cols[3].number_input("Quantity", min_value=1, value=1, step=1,
                                             key="adjust_quantity")
            movement_date = st.date_input("Adjustment date", value=date.today(), key="adjust_date")
            notes = st.text_input("Notes / adjustment reason", key="adjust_notes")
            submitted = st.form_submit_button("Record adjustment", type="primary")
        if submitted:
            submit_simple_movement(direction, product_id, warehouse_id, quantity, notes, movement_date)

st.divider()
st.subheader("Movement history")
try:
    products = list_products()
    warehouses = list_warehouses()
    product_labels = dict(zip(products["product_id"], products["sku"] + " — " + products["product_name"]))
    warehouse_labels = dict(zip(warehouses["warehouse_id"], warehouses["warehouse_name"]))
    options = st.columns(4)
    product_label = options[0].selectbox("Product filter", ["All products", *product_labels.values()])
    warehouse_label = options[1].selectbox("Warehouse filter", ["All warehouses", *warehouse_labels.values()])
    movement_type = options[2].selectbox(
        "Movement type", ["All types", "RECEIPT", "ISSUE", "TRANSFER_IN",
                          "TRANSFER_OUT", "ADJUSTMENT_IN", "ADJUSTMENT_OUT"]
    )
    date_range = options[3].date_input(
        "Movement date range", value=(date(2026, 1, 1), date.today()), key="movement_history_dates"
    )
    start_date, end_date = (date_range if isinstance(date_range, tuple) and len(date_range) == 2
                            else (None, None))
    product_id = next((key for key, label in product_labels.items() if label == product_label), "")
    warehouse_id = next((key for key, label in warehouse_labels.items() if label == warehouse_label), "")
    history = movement_history(
        product_id, warehouse_id, "" if movement_type == "All types" else movement_type,
        start_date, end_date,
    )
    st.dataframe(history, use_container_width=True, hide_index=True)
except (SQLAlchemyError, RuntimeError) as error:
    show_db_error(error)
