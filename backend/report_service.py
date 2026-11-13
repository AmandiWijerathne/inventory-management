"""Filtered report datasets and CSV/Excel export helpers."""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd

from backend.database import query_df
from backend.inventory_service import INVENTORY_SELECT
from backend.stock_movement_service import movement_history


def inventory_valuation(start_date: date | None = None, end_date: date | None = None,
                        category: str = "", warehouse_id: str = "",
                        product_id: str = "") -> pd.DataFrame:
    return query_df(
        INVENTORY_SELECT + """
        WHERE (:category = '' OR p.category=:category)
          AND (:warehouse_id = '' OR w.warehouse_id=:warehouse_id)
          AND (:product_id = '' OR p.product_id=:product_id)
          AND (:start_date IS NULL OR i.last_updated >= :start_date)
          AND (:end_date IS NULL OR i.last_updated <= :end_date)
        ORDER BY p.category, p.product_name, w.warehouse_name
        """,
        {"category": category, "warehouse_id": warehouse_id, "product_id": product_id,
         "start_date": start_date, "end_date": end_date},
    )


def supplier_inventory(warehouse_id: str = "", category: str = "",
                       product_id: str = "", start_date: date | None = None,
                       end_date: date | None = None) -> pd.DataFrame:
    return query_df(
        """
        SELECT s.supplier_name, p.category,
               COUNT(DISTINCT p.product_id) FILTER (WHERE i.product_id IS NOT NULL)
                   AS product_count,
               COALESCE(SUM(i.quantity_on_hand), 0)::BIGINT AS stock_units,
               COALESCE(SUM(i.quantity_on_hand * p.unit_cost_lkr), 0)
                   AS inventory_value_lkr
        FROM suppliers s JOIN products p USING (supplier_id)
        LEFT JOIN inventory i ON i.product_id=p.product_id
            AND (:warehouse_id = '' OR i.warehouse_id=:warehouse_id)
            AND (:start_date IS NULL OR i.last_updated>=:start_date)
            AND (:end_date IS NULL OR i.last_updated<=:end_date)
        WHERE (:category = '' OR p.category=:category)
          AND (:product_id = '' OR p.product_id=:product_id)
        GROUP BY s.supplier_id, s.supplier_name, p.category
        ORDER BY s.supplier_name, inventory_value_lkr DESC
        """,
        {"warehouse_id": warehouse_id, "category": category, "product_id": product_id,
         "start_date": start_date, "end_date": end_date},
    )


def movement_report(product_id: str = "", warehouse_id: str = "",
                    movement_type: str = "", start_date: date | None = None,
                    end_date: date | None = None, category: str = "") -> pd.DataFrame:
    return movement_history(product_id, warehouse_id, movement_type, start_date,
                            end_date, category=category)


def monthly_movement_report(start_date: date | None = None,
                            end_date: date | None = None,
                            warehouse_id: str = "", category: str = "",
                            product_id: str = "") -> pd.DataFrame:
    return query_df(
        """
        SELECT date_trunc('month', m.movement_date)::DATE AS month,
               w.warehouse_name,
               COALESCE(SUM(m.quantity) FILTER (WHERE m.movement_type='RECEIPT'), 0)::BIGINT
                   AS receipts,
               COALESCE(SUM(m.quantity) FILTER (WHERE m.movement_type='ISSUE'), 0)::BIGINT
                   AS issues
        FROM stock_movements m JOIN warehouses w USING (warehouse_id)
        JOIN products p USING (product_id)
        WHERE (:start_date IS NULL OR m.movement_date>=:start_date)
          AND (:end_date IS NULL OR m.movement_date<=:end_date)
          AND (:warehouse_id = '' OR m.warehouse_id=:warehouse_id)
          AND (:category = '' OR p.category=:category)
          AND (:product_id = '' OR p.product_id=:product_id)
        GROUP BY date_trunc('month', m.movement_date), w.warehouse_id
        ORDER BY month, w.warehouse_name
        """,
        {"start_date": start_date, "end_date": end_date, "warehouse_id": warehouse_id,
         "category": category, "product_id": product_id},
    )


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return _spreadsheet_safe(frame).to_csv(index=False).encode("utf-8-sig")


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            _spreadsheet_safe(frame).to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()


def _spreadsheet_safe(frame: pd.DataFrame) -> pd.DataFrame:
    safe = frame.copy()

    def escape(value: object) -> object:
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value

    for column in safe.select_dtypes(include=["object", "string"]).columns:
        safe[column] = safe[column].map(escape)
    return safe
