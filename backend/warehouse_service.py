"""Warehouse operations and capacity reporting."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import text

from backend.database import query_df, transaction
from backend.validation import whole_number


def list_warehouses() -> pd.DataFrame:
    return query_df("SELECT warehouse_id, warehouse_name, city, province, capacity_units "
                    "FROM warehouses ORDER BY warehouse_name")


def warehouse_summary(category: str = "", product_id: str = "",
                      warehouse_id: str = "", start_date: Any = None,
                      end_date: Any = None) -> pd.DataFrame:
    params: dict[str, Any] = {
        "category": category,
        "product_id": product_id,
        "warehouse_id": warehouse_id,
    }
    inventory_filters: list[str] = []
    if start_date is not None:
        inventory_filters.append("i.last_updated >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        inventory_filters.append("i.last_updated <= :end_date")
        params["end_date"] = end_date
    inventory_filter_clause = "".join(
        f"\n            AND {condition}" for condition in inventory_filters
    )
    return query_df(
        f"""
        SELECT w.warehouse_id, w.warehouse_name, w.city, w.province, w.capacity_units,
               COALESCE(SUM(CASE WHEN p.product_id IS NOT NULL
                                 THEN i.quantity_on_hand ELSE 0 END), 0)::BIGINT AS stock_units,
               COALESCE(SUM(CASE WHEN p.product_id IS NOT NULL
                                 THEN i.quantity_on_hand * p.unit_cost_lkr ELSE 0 END), 0)::NUMERIC(16, 2)
                   AS inventory_value_lkr,
               ROUND(100.0 * COALESCE(SUM(CASE WHEN p.product_id IS NOT NULL
                                               THEN i.quantity_on_hand ELSE 0 END), 0)
                     / NULLIF(w.capacity_units, 0), 1) AS capacity_utilization_pct
        FROM warehouses w
        LEFT JOIN inventory i ON i.warehouse_id=w.warehouse_id
            {inventory_filter_clause}
        LEFT JOIN products p ON p.product_id=i.product_id
            AND (:category='' OR p.category=:category)
            AND (:product_id='' OR p.product_id=:product_id)
        WHERE (:warehouse_id='' OR w.warehouse_id=:warehouse_id)
        GROUP BY w.warehouse_id
        ORDER BY w.warehouse_name
        """,
        params,
    )


def save_warehouse(values: dict[str, Any], warehouse_id: str | None = None) -> str:
    fields = {
        "warehouse_name": str(values["warehouse_name"]).strip(),
        "city": str(values["city"]).strip(),
        "province": str(values["province"]).strip(),
        "capacity_units": whole_number(values["capacity_units"], "Warehouse capacity", minimum=1),
    }
    if any(not fields[key] for key in ("warehouse_name", "city", "province")):
        raise ValueError("Warehouse name, city, and province are required.")
    with transaction() as connection:
        if warehouse_id:
            result = connection.execute(
                text("UPDATE warehouses SET warehouse_name=:warehouse_name, city=:city, "
                     "province=:province, capacity_units=:capacity_units "
                     "WHERE warehouse_id=:warehouse_id"),
                {**fields, "warehouse_id": warehouse_id},
            )
            if result.rowcount != 1:
                raise ValueError("The selected warehouse no longer exists.")
            return warehouse_id
        new_id = f"WH{uuid4().hex[:12].upper()}"
        connection.execute(
            text("INSERT INTO warehouses (warehouse_id, warehouse_name, city, province, capacity_units) "
                 "VALUES (:warehouse_id, :warehouse_name, :city, :province, :capacity_units)"),
            {**fields, "warehouse_id": new_id},
        )
        return new_id


def delete_warehouse(warehouse_id: str) -> None:
    with transaction() as connection:
        references = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM inventory WHERE warehouse_id=:id) OR "
                 "EXISTS (SELECT 1 FROM stock_movements WHERE warehouse_id=:id)"),
            {"id": warehouse_id},
        ).scalar_one()
        if references:
            raise ValueError("This warehouse has inventory or movement history and cannot be deleted.")
        deleted = connection.execute(
            text("DELETE FROM warehouses WHERE warehouse_id=:id"), {"id": warehouse_id}
        )
        if deleted.rowcount != 1:
            raise ValueError("The selected warehouse no longer exists.")
