"""Atomic stock receipts, issues, adjustments, and warehouse transfers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import text

from backend.database import query_df, transaction
from backend.validation import whole_number

INCREASE_TYPES = {"RECEIPT", "ADJUSTMENT_IN"}
DECREASE_TYPES = {"ISSUE", "ADJUSTMENT_OUT"}


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:16].upper()}"


def _product(connection: Any, product_id: str) -> dict[str, Any]:
    row = connection.execute(
        text("SELECT product_id, unit_cost_lkr, default_reorder_level FROM products "
             "WHERE product_id=:id"),
        {"id": product_id},
    ).mappings().first()
    if row is None:
        raise ValueError("Select an existing product.")
    return dict(row)


def _warehouse_exists(connection: Any, warehouse_id: str) -> bool:
    return bool(connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM warehouses WHERE warehouse_id=:id)"),
        {"id": warehouse_id},
    ).scalar_one())


def _ensure_inventory(connection: Any, product: dict[str, Any], warehouse_id: str) -> None:
    if not _warehouse_exists(connection, warehouse_id):
        raise ValueError("Select an existing warehouse.")
    reorder = int(product["default_reorder_level"])
    maximum = max(reorder, max(1, reorder) * 3)
    connection.execute(
        text("""
        INSERT INTO inventory (inventory_id, product_id, warehouse_id, opening_quantity,
            quantity_on_hand, reorder_level, maximum_stock_level, available_quantity,
            reserved_quantity, last_updated)
        VALUES (:inventory_id, :product_id, :warehouse_id, 0, 0, :reorder, :maximum, 0, 0, :today)
        ON CONFLICT (product_id, warehouse_id) DO NOTHING
        """),
        {"inventory_id": _new_id("INV"), "product_id": product["product_id"],
         "warehouse_id": warehouse_id, "reorder": reorder, "maximum": maximum,
         "today": date.today()},
    )


def _lock_inventory_rows(
    connection: Any, product_id: str, warehouse_ids: list[str]
) -> dict[str, dict[str, Any]]:
    binds = {f"warehouse_{index}": value for index, value in enumerate(warehouse_ids)}
    placeholders = ", ".join(f":{name}" for name in binds)
    rows = connection.execute(
        text("SELECT inventory_id, warehouse_id, quantity_on_hand, available_quantity, "
             "reserved_quantity FROM inventory WHERE product_id=:product_id "
             f"AND warehouse_id IN ({placeholders}) ORDER BY warehouse_id FOR UPDATE"),
        {"product_id": product_id, **binds},
    ).mappings().all()
    return {row["warehouse_id"]: dict(row) for row in rows}


def _write_movement(
    connection: Any, product: dict[str, Any], warehouse_id: str,
    movement_type: str, quantity: int, reference_no: str, notes: str,
    movement_date: date,
) -> None:
    connection.execute(
        text("""
        INSERT INTO stock_movements (movement_id, movement_date, product_id, warehouse_id,
            movement_type, quantity, reference_no, unit_cost_lkr, notes)
        VALUES (:movement_id, :movement_date, :product_id, :warehouse_id,
            :movement_type, :quantity, :reference_no, :unit_cost_lkr, :notes)
        """),
        {"movement_id": _new_id("MOV"), "movement_date": movement_date,
         "product_id": product["product_id"], "warehouse_id": warehouse_id,
         "movement_type": movement_type, "quantity": quantity,
         "reference_no": reference_no, "unit_cost_lkr": product["unit_cost_lkr"],
         "notes": notes.strip()},
    )


def record_movement(product_id: str, warehouse_id: str, movement_type: str,
                    quantity: int, notes: str = "", movement_date: date | None = None,
                    reference_no: str = "") -> str:
    """Apply one non-transfer movement and insert its audit row in the same transaction."""
    movement_type = movement_type.upper().strip()
    if movement_type not in INCREASE_TYPES | DECREASE_TYPES:
        raise ValueError("Choose a receipt, issue, or inventory adjustment movement type.")
    quantity = whole_number(quantity, "Movement quantity", minimum=1)
    transaction_date = movement_date or date.today()
    reference = reference_no.strip() or f"{movement_type[:3]}-{uuid4().hex[:12].upper()}"
    with transaction() as connection:
        product = _product(connection, product_id)
        if movement_type in INCREASE_TYPES:
            _ensure_inventory(connection, product, warehouse_id)
        rows = _lock_inventory_rows(connection, product_id, [warehouse_id])
        inventory = rows.get(warehouse_id)
        if inventory is None:
            raise ValueError("No inventory record exists at this warehouse for the selected product.")
        if movement_type in DECREASE_TYPES:
            if inventory["available_quantity"] < quantity:
                raise ValueError(
                    f"Insufficient available stock: {inventory['available_quantity']} units available."
                )
            sign = -1
        else:
            sign = 1
        connection.execute(
            text("UPDATE inventory SET quantity_on_hand=quantity_on_hand+:delta, "
                 "available_quantity=available_quantity+:delta, last_updated=:today "
                 "WHERE inventory_id=:inventory_id"),
            {"delta": sign * quantity, "today": date.today(),
             "inventory_id": inventory["inventory_id"]},
        )
        _write_movement(connection, product, warehouse_id, movement_type, quantity,
                        reference, notes, transaction_date)
    return reference


def transfer_stock(product_id: str, source_warehouse_id: str, destination_warehouse_id: str,
                   quantity: int, notes: str = "", movement_date: date | None = None) -> str:
    """Move stock atomically, recording paired rows with one shared reference number."""
    if source_warehouse_id == destination_warehouse_id:
        raise ValueError("Source and destination warehouses must be different.")
    quantity = whole_number(quantity, "Transfer quantity", minimum=1)
    transaction_date = movement_date or date.today()
    reference = f"TRF-{uuid4().hex[:16].upper()}"
    with transaction() as connection:
        product = _product(connection, product_id)
        _ensure_inventory(connection, product, destination_warehouse_id)
        rows = _lock_inventory_rows(
            connection, product_id, [source_warehouse_id, destination_warehouse_id]
        )
        source = rows.get(source_warehouse_id)
        destination = rows.get(destination_warehouse_id)
        if source is None or destination is None:
            raise ValueError("Source stock is not recorded at the selected warehouse.")
        if source["available_quantity"] < quantity:
            raise ValueError(
                f"Insufficient available stock: {source['available_quantity']} units available."
            )
        connection.execute(
            text("UPDATE inventory SET quantity_on_hand=quantity_on_hand-:quantity, "
                 "available_quantity=available_quantity-:quantity, last_updated=:today "
                 "WHERE inventory_id=:inventory_id"),
            {"quantity": quantity, "today": date.today(),
             "inventory_id": source["inventory_id"]},
        )
        connection.execute(
            text("UPDATE inventory SET quantity_on_hand=quantity_on_hand+:quantity, "
                 "available_quantity=available_quantity+:quantity, last_updated=:today "
                 "WHERE inventory_id=:inventory_id"),
            {"quantity": quantity, "today": date.today(),
             "inventory_id": destination["inventory_id"]},
        )
        _write_movement(connection, product, source_warehouse_id, "TRANSFER_OUT", quantity,
                        reference, notes, transaction_date)
        _write_movement(connection, product, destination_warehouse_id, "TRANSFER_IN", quantity,
                        reference, notes, transaction_date)
    return reference


def movement_history(product_id: str = "", warehouse_id: str = "", movement_type: str = "",
                     start_date: date | None = None, end_date: date | None = None,
                     limit: int | None = None, category: str = "") -> pd.DataFrame:
    limit_clause = "LIMIT :limit" if limit else ""
    date_filters: list[str] = []
    params: dict[str, Any] = {
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "movement_type": movement_type,
        "category": category,
        "limit": limit,
    }
    if start_date is not None:
        date_filters.append("m.movement_date >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        date_filters.append("m.movement_date <= :end_date")
        params["end_date"] = end_date
    date_filter_clause = "".join(f"\n          AND {condition}" for condition in date_filters)
    return query_df(
        f"""
        SELECT m.movement_id, m.movement_date, m.product_id, p.sku, p.product_name,
               m.warehouse_id, w.warehouse_name, m.movement_type, m.quantity,
               m.reference_no, m.unit_cost_lkr, m.quantity * m.unit_cost_lkr AS movement_value_lkr,
               m.notes
        FROM stock_movements m
        JOIN products p USING (product_id)
        JOIN warehouses w USING (warehouse_id)
        WHERE (:product_id = '' OR m.product_id=:product_id)
          AND (:warehouse_id = '' OR m.warehouse_id=:warehouse_id)
          AND (:movement_type = '' OR m.movement_type=:movement_type)
          AND (:category = '' OR p.category=:category)
          {date_filter_clause}
        ORDER BY m.movement_date DESC, m.movement_id DESC
        """ + limit_clause,
        params,
    )
