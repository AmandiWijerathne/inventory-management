"""Validate and import the supplied CSV dataset without overwriting existing rows."""

from __future__ import annotations

import argparse
import logging
import os
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TABLE_FILES = {
    "suppliers": "suppliers.csv",
    "warehouses": "warehouses.csv",
    "products": "products.csv",
    "inventory": "inventory.csv",
    "stock_movements": "stock_movements.csv",
}
INSERTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "suppliers": (
        "INSERT INTO suppliers (supplier_id, supplier_name, city, specialization) "
        "VALUES (:supplier_id, :supplier_name, :city, :specialization) "
        "ON CONFLICT DO NOTHING",
        ("supplier_id", "supplier_name", "city", "specialization"),
    ),
    "warehouses": (
        "INSERT INTO warehouses (warehouse_id, warehouse_name, city, province, capacity_units) "
        "VALUES (:warehouse_id, :warehouse_name, :city, :province, :capacity_units) "
        "ON CONFLICT DO NOTHING",
        ("warehouse_id", "warehouse_name", "city", "province", "capacity_units"),
    ),
    "products": (
        "INSERT INTO products (product_id, sku, product_name, product_type, category, "
        "unit_of_measure, unit_cost_lkr, default_reorder_level, lead_time_days, supplier_id) "
        "VALUES (:product_id, :sku, :product_name, :product_type, :category, "
        ":unit_of_measure, :unit_cost_lkr, :default_reorder_level, :lead_time_days, :supplier_id) "
        "ON CONFLICT DO NOTHING",
        ("product_id", "sku", "product_name", "product_type", "category", "unit_of_measure",
         "unit_cost_lkr", "default_reorder_level", "lead_time_days", "supplier_id"),
    ),
    "inventory": (
        "INSERT INTO inventory (inventory_id, product_id, warehouse_id, opening_quantity, "
        "quantity_on_hand, reorder_level, maximum_stock_level, available_quantity, "
        "reserved_quantity, last_updated) VALUES (:inventory_id, :product_id, :warehouse_id, "
        ":opening_quantity, :quantity_on_hand, :reorder_level, :maximum_stock_level, "
        ":available_quantity, :reserved_quantity, :last_updated) ON CONFLICT DO NOTHING",
        ("inventory_id", "product_id", "warehouse_id", "opening_quantity", "quantity_on_hand",
         "reorder_level", "maximum_stock_level", "available_quantity", "reserved_quantity",
         "last_updated"),
    ),
    "stock_movements": (
        "INSERT INTO stock_movements (movement_id, movement_date, product_id, warehouse_id, "
        "movement_type, quantity, reference_no, unit_cost_lkr, notes) VALUES (:movement_id, "
        ":movement_date, :product_id, :warehouse_id, :movement_type, :quantity, :reference_no, "
        ":unit_cost_lkr, :notes) ON CONFLICT DO NOTHING",
        ("movement_id", "movement_date", "product_id", "warehouse_id", "movement_type",
         "quantity", "reference_no", "unit_cost_lkr", "notes"),
    ),
}


def _read_csv(file_name: str) -> list[dict[str, str]]:
    path = DATA_DIR / file_name
    if not path.is_file():
        raise FileNotFoundError(f"Required dataset file was not found: {path}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if frame.empty:
        raise ValueError(f"{file_name} contains no data rows.")
    return frame.to_dict(orient="records")


def load_and_validate_dataset() -> dict[str, list[dict[str, Any]]]:
    """Read the original CSVs, verify keys/relationships and inventory reconciliation."""
    raw = {table: _read_csv(file_name) for table, file_name in TABLE_FILES.items()}
    tables: dict[str, list[dict[str, Any]]] = {}
    for table, rows in raw.items():
        expected = set(INSERTS[table][1])
        missing = expected.difference(rows[0])
        if missing:
            raise ValueError(f"{TABLE_FILES[table]} is missing required columns: {sorted(missing)}")
        tables[table] = [{key: row[key] for key in INSERTS[table][1]} for row in rows]

    key_columns = {
        "suppliers": ("supplier_id",),
        "warehouses": ("warehouse_id",),
        "products": ("product_id", "sku"),
        "inventory": ("inventory_id",),
        "stock_movements": ("movement_id",),
    }
    for table, columns in key_columns.items():
        for column in columns:
            values = [row[column] for row in tables[table]]
            if not all(values) or len(values) != len(set(values)):
                raise ValueError(f"{table}.{column} contains empty or duplicate identifiers.")

    supplier_ids = {row["supplier_id"] for row in tables["suppliers"]}
    product_ids = {row["product_id"] for row in tables["products"]}
    warehouse_ids = {row["warehouse_id"] for row in tables["warehouses"]}
    if any(row["supplier_id"] not in supplier_ids for row in tables["products"]):
        raise ValueError("A product refers to a supplier absent from the source dataset.")
    if any(row["product_id"] not in product_ids or row["warehouse_id"] not in warehouse_ids
           for row in tables["inventory"] + tables["stock_movements"]):
        raise ValueError("An inventory or movement record refers to a missing entity.")
    pairs = [(row["product_id"], row["warehouse_id"]) for row in tables["inventory"]]
    if len(pairs) != len(set(pairs)):
        raise ValueError("The dataset contains duplicate product/warehouse inventory records.")

    for row in tables["products"]:
        row["unit_cost_lkr"] = Decimal(row["unit_cost_lkr"])
        row["default_reorder_level"] = int(row["default_reorder_level"])
        row["lead_time_days"] = int(row["lead_time_days"])
    for row in tables["warehouses"]:
        row["capacity_units"] = int(row["capacity_units"])
    for row in tables["inventory"]:
        for column in (
            "opening_quantity", "quantity_on_hand", "reorder_level",
            "maximum_stock_level", "available_quantity", "reserved_quantity",
        ):
            row[column] = int(row[column])
        row["last_updated"] = date.fromisoformat(row["last_updated"])
        if row["available_quantity"] + row["reserved_quantity"] != row["quantity_on_hand"]:
            raise ValueError(f"Inventory row {row['inventory_id']} has an inconsistent quantity split.")
        if row["maximum_stock_level"] < row["reorder_level"]:
            raise ValueError(f"Inventory row {row['inventory_id']} has invalid stock thresholds.")
    for row in tables["stock_movements"]:
        row["movement_date"] = date.fromisoformat(row["movement_date"])
        row["quantity"] = int(row["quantity"])
        row["unit_cost_lkr"] = Decimal(row["unit_cost_lkr"])
        if row["quantity"] <= 0:
            raise ValueError(f"Movement {row['movement_id']} must have a positive quantity.")
        if row["unit_cost_lkr"] < 0:
            raise ValueError(f"Movement {row['movement_id']} has a negative unit cost.")
        if row["movement_type"] not in {
            "RECEIPT", "ISSUE", "TRANSFER_IN", "TRANSFER_OUT",
            "ADJUSTMENT_IN", "ADJUSTMENT_OUT",
        }:
            raise ValueError(f"Movement {row['movement_id']} has an unsupported type.")

    signed_movements: defaultdict[tuple[str, str], int] = defaultdict(int)
    transfer_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    increases = {"RECEIPT", "TRANSFER_IN", "ADJUSTMENT_IN"}
    for row in tables["stock_movements"]:
        direction = 1 if row["movement_type"] in increases else -1
        signed_movements[(row["product_id"], row["warehouse_id"])] += direction * row["quantity"]
        if row["movement_type"] in {"TRANSFER_IN", "TRANSFER_OUT"}:
            transfer_groups[row["reference_no"]].append(row)
    for row in tables["inventory"]:
        calculated = row["opening_quantity"] + signed_movements[
            (row["product_id"], row["warehouse_id"])
        ]
        if calculated != row["quantity_on_hand"]:
            raise ValueError(
                f"Inventory row {row['inventory_id']} does not reconcile with its movement history."
            )
    for reference, rows in transfer_groups.items():
        types = Counter(row["movement_type"] for row in rows)
        if (
            len(rows) != 2
            or types != Counter({"TRANSFER_IN": 1, "TRANSFER_OUT": 1})
            or len({(row["product_id"], row["quantity"]) for row in rows}) != 1
        ):
            raise ValueError(f"Transfer reference {reference} does not contain a matching pair.")
    logger.info(
        "Validated source rows: %s",
        {table: len(rows) for table, rows in tables.items()},
    )
    return tables


def import_dataset(database_url: str) -> dict[str, int]:
    """Insert source records in FK order; conflicts are preserved, never updated."""
    tables = load_and_validate_dataset()
    engine = create_engine(database_url, pool_pre_ping=True)
    inserted: dict[str, int] = {}
    try:
        with engine.begin() as connection:
            for table, rows in tables.items():
                statement, columns = INSERTS[table]
                result = connection.execute(
                    text(statement),
                    [{column: row[column] for column in columns} for row in rows],
                )
                inserted[table] = max(result.rowcount, 0)
    finally:
        engine.dispose()
    for table, count in inserted.items():
        logger.info("%s: inserted %d of %d source rows; existing conflicts unchanged.",
                    table, count, len(tables[table]))
    return inserted


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate dataset files without connecting to PostgreSQL.")
    args = parser.parse_args()
    if args.validate_only:
        tables = load_and_validate_dataset()
        print("Dataset validation passed:", {table: len(rows) for table, rows in tables.items()})
        return
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing. Configure it in the project .env file.")
    import_dataset(database_url)


if __name__ == "__main__":
    main()
