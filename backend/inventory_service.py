"""Inventory queries, derived statuses, valuation, and replenishment suggestions."""

from __future__ import annotations

import pandas as pd
from datetime import date

from backend.database import query_df

INVENTORY_SELECT = """
    SELECT i.inventory_id, i.product_id, p.sku, p.product_name, p.category,
           p.unit_cost_lkr, p.supplier_id, s.supplier_name,
           i.warehouse_id, w.warehouse_name, i.opening_quantity, i.quantity_on_hand,
           i.available_quantity, i.reserved_quantity, i.reorder_level,
           i.maximum_stock_level, i.last_updated,
           i.quantity_on_hand * p.unit_cost_lkr AS inventory_value_lkr,
           CASE
             WHEN i.quantity_on_hand = 0 THEN 'Out of Stock'
             WHEN i.quantity_on_hand > i.maximum_stock_level THEN 'Overstock'
             WHEN i.quantity_on_hand <= i.reorder_level THEN 'Low Stock'
             ELSE 'In Stock'
           END AS inventory_status
    FROM inventory i
    JOIN products p USING (product_id)
    JOIN warehouses w USING (warehouse_id)
    JOIN suppliers s USING (supplier_id)
"""


def list_inventory(search: str = "", category: str = "", warehouse_id: str = "",
                   status: str = "", sort_by: str = "product_name",
                   ascending: bool = True) -> pd.DataFrame:
    allowed_sort = {
        "product_name", "warehouse_name", "quantity_on_hand", "inventory_value_lkr",
        "reorder_level", "last_updated",
    }
    sort_column = sort_by if sort_by in allowed_sort else "product_name"
    direction = "ASC" if ascending else "DESC"
    return query_df(
        INVENTORY_SELECT + f"""
        WHERE (:search = '' OR p.product_name ILIKE :pattern OR p.sku ILIKE :pattern)
          AND (:category = '' OR p.category = :category)
          AND (:warehouse_id = '' OR w.warehouse_id = :warehouse_id)
          AND (:status = '' OR
               CASE WHEN i.quantity_on_hand = 0 THEN 'Out of Stock'
                    WHEN i.quantity_on_hand > i.maximum_stock_level THEN 'Overstock'
                    WHEN i.quantity_on_hand <= i.reorder_level THEN 'Low Stock'
                    ELSE 'In Stock' END = :status)
        ORDER BY {sort_column} {direction}, p.product_name, w.warehouse_name
        """,
        {"search": search.strip(), "pattern": f"%{search.strip()}%",
         "category": category, "warehouse_id": warehouse_id, "status": status},
    )


def inventory_alerts(warehouse_id: str = "", start_date: date | None = None,
                     end_date: date | None = None) -> pd.DataFrame:
    params: dict[str, object] = {"warehouse_id": warehouse_id}
    date_filters: list[str] = []
    if start_date is not None:
        date_filters.append("i.last_updated >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        date_filters.append("i.last_updated <= :end_date")
        params["end_date"] = end_date
    date_filter_clause = "".join(f"\n          AND {condition}" for condition in date_filters)
    return query_df(
        INVENTORY_SELECT + f"""
        WHERE (i.quantity_on_hand = 0
           OR (i.quantity_on_hand <= i.reorder_level AND i.quantity_on_hand > 0)
           OR i.quantity_on_hand > i.maximum_stock_level)
          AND (:warehouse_id = '' OR w.warehouse_id = :warehouse_id)
          {date_filter_clause}
        ORDER BY CASE WHEN i.quantity_on_hand = 0 THEN 0 ELSE 1 END,
                 i.quantity_on_hand, p.product_name
        """,
        params,
    )


def replenishment_recommendations(warehouse_id: str = "", start_date: date | None = None,
                                  end_date: date | None = None) -> pd.DataFrame:
    alerts = inventory_alerts(warehouse_id, start_date, end_date)
    if alerts.empty:
        alerts["recommended_replenishment"] = pd.Series(dtype="int64")
        return alerts
    alerts["recommended_replenishment"] = (
        alerts["maximum_stock_level"] - alerts["quantity_on_hand"]
    ).clip(lower=0).astype("int64")
    return alerts[alerts["inventory_status"].isin(["Low Stock", "Out of Stock"])].copy()
