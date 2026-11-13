import logging

import plotly.express as px
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from backend.inventory_service import list_inventory
from backend.warehouse_service import (
    delete_warehouse,
    list_warehouses,
    save_warehouse,
    warehouse_summary,
)
from frontend.ui import currency, page_header, show_db_error

logger = logging.getLogger(__name__)
page_header("Warehouse management", "Manage locations, stock distribution, valuation, and indicative capacity utilization.", "🏭")

try:
    warehouses = warehouse_summary()
except (SQLAlchemyError, RuntimeError) as error:
    show_db_error(error)
    st.stop()

if warehouses.empty:
    st.info("No warehouses are configured.")
else:
    st.subheader("Warehouse overview")
    display = warehouses[["warehouse_name", "city", "province", "capacity_units",
                         "stock_units", "inventory_value_lkr", "capacity_utilization_pct"]].copy()
    display.columns = ["Warehouse", "City", "Province", "Capacity (units)", "Stock (units)",
                       "Inventory value (LKR)", "Utilization (%)"]
    st.dataframe(
        display.style.format({
            "Inventory value (LKR)": lambda value: currency(value, 2),
            "Utilization (%)": "{:.1f}%",
        }),
        use_container_width=True, hide_index=True,
    )
    left, right = st.columns(2)
    with left:
        st.subheader("Stock distribution")
        fig = px.bar(warehouses, x="warehouse_name", y="stock_units", color="warehouse_name",
                     labels={"warehouse_name": "Warehouse", "stock_units": "Units", "color": ""},
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(showlegend=False, xaxis_title="", height=320)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Indicative capacity utilization")
        st.caption("Calculated as total units on hand ÷ configured capacity units. This is a unit-count estimate, not volume or pallet utilization.")
        for _, row in warehouses.iterrows():
            pct = float(row["capacity_utilization_pct"] or 0)
            st.markdown(f"**{row['warehouse_name']}** · {pct:.1f}%")
            st.progress(min(max(pct / 100, 0), 1))
            if pct > 100:
                st.warning(f"Stock exceeds configured unit capacity by {pct - 100:.1f}%.")
    st.subheader("Product stock at a warehouse")
    selected_warehouse = st.selectbox(
        "View warehouse stock", warehouses["warehouse_id"].tolist(),
        format_func=lambda value: warehouses.loc[
            warehouses.warehouse_id == value, "warehouse_name"
        ].iloc[0],
    )
    try:
        stock = list_inventory(warehouse_id=selected_warehouse)
        st.dataframe(
            stock[["sku", "product_name", "category", "quantity_on_hand",
                   "available_quantity", "reserved_quantity", "inventory_status",
                   "inventory_value_lkr"]],
            use_container_width=True, hide_index=True,
        )
    except (SQLAlchemyError, RuntimeError) as error:
        show_db_error(error)

st.divider()
add_tab, edit_tab = st.tabs(["Add warehouse", "Update or delete"])
with add_tab:
    with st.form("add_warehouse_form", clear_on_submit=True):
        cols = st.columns(4)
        name = cols[0].text_input("Warehouse name *")
        city = cols[1].text_input("City *")
        province = cols[2].text_input("Province *")
        capacity = cols[3].number_input("Capacity (units) *", min_value=1, value=100, step=25)
        submitted = st.form_submit_button("Add warehouse", type="primary")
    if submitted:
        try:
            new_id = save_warehouse({
                "warehouse_name": name, "city": city, "province": province,
                "capacity_units": capacity,
            })
            st.success(f"Warehouse created ({new_id}).")
            st.rerun()
        except ValueError as error:
            st.error(str(error))
        except (SQLAlchemyError, RuntimeError) as error:
            show_db_error(error)

with edit_tab:
    if warehouses.empty:
        st.info("There are no warehouses to edit.")
    else:
        selected_id = st.selectbox(
            "Choose a warehouse", warehouses["warehouse_id"].tolist(),
            format_func=lambda value: warehouses.loc[
                warehouses.warehouse_id == value, "warehouse_name"
            ].iloc[0],
        )
        selected = warehouses.loc[warehouses.warehouse_id == selected_id].iloc[0]
        with st.form("edit_warehouse_form"):
            cols = st.columns(4)
            edit_name = cols[0].text_input("Warehouse name", value=selected["warehouse_name"])
            edit_city = cols[1].text_input("City", value=selected["city"])
            edit_province = cols[2].text_input("Province", value=selected["province"])
            edit_capacity = cols[3].number_input(
                "Capacity (units)", min_value=1, value=int(selected["capacity_units"]), step=25
            )
            saved = st.form_submit_button("Save warehouse", type="primary")
        if saved:
            try:
                save_warehouse({
                    "warehouse_name": edit_name, "city": edit_city, "province": edit_province,
                    "capacity_units": edit_capacity,
                }, selected_id)
                st.success("Warehouse updated.")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
            except (SQLAlchemyError, RuntimeError) as error:
                show_db_error(error)
        with st.expander("Delete warehouse"):
            st.warning("A warehouse with inventory or movement history cannot be deleted.")
            confirmed = st.checkbox(
                "I understand this action cannot be undone.", key="confirm_warehouse_delete"
            )
            if st.button("Delete selected warehouse", key="delete_warehouse", disabled=not confirmed):
                try:
                    delete_warehouse(selected_id)
                    st.success("Warehouse deleted.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
                except (SQLAlchemyError, RuntimeError) as error:
                    show_db_error(error)
