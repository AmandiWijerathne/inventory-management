"""Product and supplier operations."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import text

from backend.database import query_df, transaction
from backend.validation import nonnegative_money, whole_number


def list_products(search: str = "", category: str = "", supplier_id: str = "") -> pd.DataFrame:
    return query_df(
        """
        SELECT p.product_id, p.sku, p.product_name, p.product_type, p.category,
               p.unit_of_measure, p.unit_cost_lkr, p.default_reorder_level,
               p.lead_time_days, p.supplier_id, s.supplier_name
        FROM products p JOIN suppliers s USING (supplier_id)
        WHERE (:search = '' OR p.product_name ILIKE :pattern OR p.sku ILIKE :pattern)
          AND (:category = '' OR p.category = :category)
          AND (:supplier_id = '' OR p.supplier_id = :supplier_id)
        ORDER BY p.product_name
        """,
        {"search": search.strip(), "pattern": f"%{search.strip()}%",
         "category": category, "supplier_id": supplier_id},
    )


def list_suppliers() -> pd.DataFrame:
    return query_df("SELECT supplier_id, supplier_name FROM suppliers ORDER BY supplier_name")


def list_categories() -> list[str]:
    return query_df("SELECT DISTINCT category FROM products ORDER BY category")["category"].tolist()


def save_product(values: dict[str, Any], product_id: str | None = None) -> str:
    fields = {
        "sku": str(values["sku"]).strip(),
        "product_name": str(values["product_name"]).strip(),
        "product_type": str(values["product_type"]).strip(),
        "category": str(values["category"]).strip(),
        "unit_of_measure": str(values["unit_of_measure"]).strip(),
        "unit_cost_lkr": nonnegative_money(values["unit_cost_lkr"], "Unit cost"),
        "default_reorder_level": whole_number(values["default_reorder_level"], "Reorder level"),
        "lead_time_days": whole_number(values["lead_time_days"], "Lead time"),
        "supplier_id": str(values["supplier_id"]),
    }
    if any(not str(fields[key]).strip() for key in
           ("sku", "product_name", "product_type", "category", "unit_of_measure", "supplier_id")):
        raise ValueError("All product text fields are required.")
    with transaction() as connection:
        if product_id:
            result = connection.execute(
                text("UPDATE products SET sku=:sku, product_name=:product_name, "
                     "product_type=:product_type, category=:category, "
                     "unit_of_measure=:unit_of_measure, unit_cost_lkr=:unit_cost_lkr, "
                     "default_reorder_level=:default_reorder_level, lead_time_days=:lead_time_days, "
                     "supplier_id=:supplier_id WHERE product_id=:product_id"),
                {**fields, "product_id": product_id},
            )
            if result.rowcount != 1:
                raise ValueError("The selected product no longer exists.")
            return product_id
        new_id = f"PRD{uuid4().hex[:12].upper()}"
        connection.execute(
            text("INSERT INTO products (product_id, sku, product_name, product_type, category, "
                 "unit_of_measure, unit_cost_lkr, default_reorder_level, lead_time_days, supplier_id) "
                 "VALUES (:product_id, :sku, :product_name, :product_type, :category, "
                 ":unit_of_measure, :unit_cost_lkr, :default_reorder_level, :lead_time_days, :supplier_id)"),
            {**fields, "product_id": new_id},
        )
        return new_id


def delete_product(product_id: str) -> None:
    with transaction() as connection:
        references = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM inventory WHERE product_id=:id) OR "
                 "EXISTS (SELECT 1 FROM stock_movements WHERE product_id=:id)"),
            {"id": product_id},
        ).scalar_one()
        if references:
            raise ValueError("This product has inventory or movement history and cannot be deleted.")
        deleted = connection.execute(
            text("DELETE FROM products WHERE product_id=:id"), {"id": product_id}
        )
        if deleted.rowcount != 1:
            raise ValueError("The selected product no longer exists.")
