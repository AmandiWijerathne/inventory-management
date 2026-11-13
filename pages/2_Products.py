import logging

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from backend.product_service import (
    delete_product,
    list_categories,
    list_products,
    list_suppliers,
    save_product,
)
from frontend.ui import currency, page_header, show_db_error

logger = logging.getLogger(__name__)
page_header("Product management", "Maintain the product catalogue, costs, reorder defaults, and supplier links.", "📦")

try:
    suppliers = list_suppliers()
    categories = list_categories()
    search_col, category_col, supplier_col = st.columns([1.2, 1, 1])
    search = search_col.text_input("Search products", placeholder="Product name or SKU")
    category = category_col.selectbox("Category filter", ["All categories", *categories])
    supplier_names = dict(zip(suppliers["supplier_name"], suppliers["supplier_id"]))
    supplier_name = supplier_col.selectbox("Supplier filter", ["All suppliers", *supplier_names])
    product_frame = list_products(
        search, "" if category == "All categories" else category,
        "" if supplier_name == "All suppliers" else supplier_names[supplier_name],
    )
except (SQLAlchemyError, RuntimeError) as error:
    show_db_error(error)
    st.stop()

st.subheader(f"Products  ·  {len(product_frame):,}")
if product_frame.empty:
    st.info("No products match these filters.")
else:
    display = product_frame[["sku", "product_name", "category", "product_type",
                             "supplier_name", "unit_cost_lkr", "default_reorder_level",
                             "lead_time_days"]].copy()
    display.columns = ["SKU", "Product", "Category", "Type", "Supplier",
                       "Unit cost (LKR)", "Default reorder level", "Lead time (days)"]
    st.dataframe(
        display.style.format({"Unit cost (LKR)": lambda value: currency(value, 2)}),
        use_container_width=True, hide_index=True,
    )

supplier_ids = suppliers["supplier_id"].tolist()
supplier_labels = dict(zip(suppliers["supplier_id"], suppliers["supplier_name"]))
if not supplier_ids:
    st.warning("Add a supplier directly to the database before creating products.")
else:
    st.divider()
    add_tab, edit_tab = st.tabs(["Add product", "Edit or delete"])
    with add_tab:
        with st.form("add_product_form", clear_on_submit=True):
            st.markdown("#### Product details")
            cols = st.columns(3)
            sku = cols[0].text_input("SKU *")
            name = cols[1].text_input("Product name *")
            product_type = cols[2].text_input("Product type *")
            category_new = cols[0].text_input("Category *")
            unit = cols[1].text_input("Unit of measure *", value="units")
            supplier_id = cols[2].selectbox("Supplier *", supplier_ids,
                                             format_func=lambda value: supplier_labels[value])
            unit_cost = cols[0].number_input("Unit cost (LKR) *", min_value=0.0, step=100.0)
            reorder = cols[1].number_input("Default reorder level *", min_value=0, step=1)
            lead = cols[2].number_input("Lead time (days) *", min_value=0, step=1)
            submitted = st.form_submit_button("Add product", type="primary")
        if submitted:
            try:
                new_id = save_product({
                    "sku": sku, "product_name": name, "product_type": product_type,
                    "category": category_new, "unit_of_measure": unit,
                    "unit_cost_lkr": unit_cost, "default_reorder_level": reorder,
                    "lead_time_days": lead, "supplier_id": supplier_id,
                })
                st.success(f"Product created ({new_id}).")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
            except (SQLAlchemyError, RuntimeError) as error:
                show_db_error(error)
    with edit_tab:
        if product_frame.empty:
            st.info("There are no products to edit.")
        else:
            selected_id = st.selectbox(
                "Choose a product",
                product_frame["product_id"].tolist(),
                format_func=lambda value: (
                    f"{product_frame.loc[product_frame.product_id == value, 'sku'].iloc[0]} — "
                    f"{product_frame.loc[product_frame.product_id == value, 'product_name'].iloc[0]}"
                ),
            )
            selected = product_frame.loc[product_frame["product_id"] == selected_id].iloc[0]
            with st.form("edit_product_form"):
                cols = st.columns(3)
                edit_sku = cols[0].text_input("SKU", value=selected["sku"])
                edit_name = cols[1].text_input("Product name", value=selected["product_name"])
                edit_type = cols[2].text_input("Product type", value=selected["product_type"])
                edit_category = cols[0].text_input("Category", value=selected["category"])
                edit_unit = cols[1].text_input("Unit of measure", value=selected["unit_of_measure"])
                supplier_index = supplier_ids.index(selected["supplier_id"])
                edit_supplier = cols[2].selectbox(
                    "Supplier", supplier_ids, index=supplier_index,
                    format_func=lambda value: supplier_labels[value],
                )
                edit_cost = cols[0].number_input(
                    "Unit cost (LKR)", min_value=0.0, value=float(selected["unit_cost_lkr"]), step=100.0
                )
                edit_reorder = cols[1].number_input(
                    "Default reorder level", min_value=0, value=int(selected["default_reorder_level"]), step=1
                )
                edit_lead = cols[2].number_input(
                    "Lead time (days)", min_value=0, value=int(selected["lead_time_days"]), step=1
                )
                saved = st.form_submit_button("Save changes", type="primary")
            if saved:
                try:
                    save_product({
                        "sku": edit_sku, "product_name": edit_name, "product_type": edit_type,
                        "category": edit_category, "unit_of_measure": edit_unit,
                        "unit_cost_lkr": edit_cost, "default_reorder_level": edit_reorder,
                        "lead_time_days": edit_lead, "supplier_id": edit_supplier,
                    }, selected_id)
                    st.success("Product updated.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
                except (SQLAlchemyError, RuntimeError) as error:
                    show_db_error(error)
            with st.expander("Delete product"):
                st.warning("Products with inventory or movement history cannot be deleted.")
                confirmed = st.checkbox("I understand this action cannot be undone.", key="confirm_product_delete")
                if st.button("Delete selected product", key="delete_product", disabled=not confirmed):
                    try:
                        delete_product(selected_id)
                        st.success("Product deleted.")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))
                    except (SQLAlchemyError, RuntimeError) as error:
                        show_db_error(error)
