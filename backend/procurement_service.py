"""Purchase-order management, receiving workflows, and procurement analytics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import text

from backend.database import query_df, transaction
from backend.validation import nonnegative_money, whole_number

VALID_PO_STATUSES = {
    "Draft",
    "Pending Approval",
    "Approved",
    "Ordered",
    "Partially Received",
    "Received",
    "Cancelled",
}

PO_STATUS_TRANSITIONS = {
    "Draft": {"Pending Approval", "Cancelled"},
    "Pending Approval": {"Draft", "Approved", "Cancelled"},
    "Approved": {"Ordered", "Cancelled"},
    "Ordered": {"Partially Received", "Received", "Cancelled"},
    "Partially Received": {"Received"},
    "Received": set(),
    "Cancelled": set(),
}


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:16].upper()}"


def _next_po_number() -> str:
    return f"PO-{date.today().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"


def _next_receipt_number() -> str:
    return f"GR-{date.today().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"


def _supplier_exists(connection: Any, supplier_id: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM suppliers WHERE supplier_id=:supplier_id)"),
            {"supplier_id": supplier_id},
        ).scalar_one()
    )


def _warehouse_exists(connection: Any, warehouse_id: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM warehouses WHERE warehouse_id=:warehouse_id)"),
            {"warehouse_id": warehouse_id},
        ).scalar_one()
    )


def _ensure_inventory_for_receipt(connection: Any, product_id: str, warehouse_id: str) -> None:
    row = connection.execute(
        text(
            "SELECT product_id, default_reorder_level, unit_cost_lkr FROM products "
            "WHERE product_id=:product_id"
        ),
        {"product_id": product_id},
    ).mappings().first()
    if row is None:
        raise ValueError("Select an existing product.")
    reorder = int(row["default_reorder_level"])
    maximum = max(reorder, max(1, reorder) * 3)
    connection.execute(
        text(
            """
            INSERT INTO inventory (
                inventory_id, product_id, warehouse_id, opening_quantity,
                quantity_on_hand, reorder_level, maximum_stock_level,
                available_quantity, reserved_quantity, last_updated
            )
            VALUES (:inventory_id, :product_id, :warehouse_id, 0, 0, :reorder, :maximum, 0, 0, :today)
            ON CONFLICT (product_id, warehouse_id) DO NOTHING
            """
        ),
        {
            "inventory_id": _new_id("INV"),
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "reorder": reorder,
            "maximum": maximum,
            "today": date.today(),
        },
    )


def _validate_po_status(status: str) -> str:
    normalized = (status or "").strip()
    if normalized not in VALID_PO_STATUSES:
        raise ValueError(
            "Status must be one of: Draft, Pending Approval, Approved, Ordered, "
            "Partially Received, Received, Cancelled."
        )
    return normalized


def create_purchase_order(
    supplier_id: str,
    items: list[dict[str, Any]],
    order_date: date | None = None,
    expected_delivery_date: date | None = None,
    notes: str = "",
    status: str = "Draft",
) -> str:
    """Create a purchase order with line items and return its order number."""
    items = items or []
    if not items:
        raise ValueError("Add at least one product to the purchase order.")
    order_date = order_date or date.today()
    if expected_delivery_date is not None and expected_delivery_date < order_date:
        raise ValueError("Expected delivery date cannot be before the order date.")
    normalized_status = _validate_po_status(status)
    if normalized_status != "Draft":
        raise ValueError("A purchase order must be created with Draft status.")
    total_amount = Decimal("0")
    po_id = _new_id("PO")
    po_number = _next_po_number()
    item_rows: list[dict[str, Any]] = []
    with transaction() as connection:
        if not _supplier_exists(connection, supplier_id):
            raise ValueError("Select an existing supplier.")
        for entry in items:
            product_id = str(entry["product_id"]).strip()
            quantity = whole_number(entry.get("quantity"), "Order quantity", minimum=1)
            unit_price = nonnegative_money(entry.get("unit_price_lkr", 0), "Purchase unit price")
            product_row = connection.execute(
                text(
                    "SELECT product_id, product_name, supplier_id, unit_cost_lkr FROM products "
                    "WHERE product_id=:product_id"
                ),
                {"product_id": product_id},
            ).mappings().first()
            if product_row is None:
                raise ValueError("Select an existing product.")
            if product_row["supplier_id"] != supplier_id:
                raise ValueError(
                    f"Product {product_row['product_name']} is not supplied by the selected supplier."
                )
            line_total = Decimal(quantity) * unit_price
            total_amount += line_total
            item_rows.append({
                "purchase_order_item_id": _new_id("POI"),
                "purchase_order_id": po_id,
                "product_id": product_id,
                "quantity": quantity,
                "unit_price_lkr": unit_price,
                "line_total_lkr": line_total,
            })
        connection.execute(
            text(
                """
                INSERT INTO purchase_orders (
                    purchase_order_id, purchase_order_no, supplier_id,
                    order_date, expected_delivery_date, status, notes,
                    total_amount_lkr, created_at, updated_at
                )
                VALUES (:purchase_order_id, :purchase_order_no, :supplier_id,
                    :order_date, :expected_delivery_date, :status, :notes,
                    :total_amount_lkr, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {
                "purchase_order_id": po_id,
                "purchase_order_no": po_number,
                "supplier_id": supplier_id,
                "order_date": order_date,
                "expected_delivery_date": expected_delivery_date,
                "status": normalized_status,
                "notes": notes.strip(),
                "total_amount_lkr": total_amount,
            },
        )
        for item in item_rows:
            connection.execute(
                text(
                    """
                    INSERT INTO purchase_order_items (
                        purchase_order_item_id, purchase_order_id, product_id,
                        quantity, unit_price_lkr, received_quantity, line_total_lkr
                    )
                    VALUES (:purchase_order_item_id, :purchase_order_id, :product_id,
                        :quantity, :unit_price_lkr, 0, :line_total_lkr)
                    """
                ),
                item,
            )
    return po_number


def list_purchase_orders(
    supplier_id: str = "",
    status: str = "",
    search: str = "",
) -> pd.DataFrame:
    normalized_search = search.strip()
    return query_df(
        """
        SELECT po.purchase_order_id, po.purchase_order_no, po.supplier_id,
               s.supplier_name, po.order_date, po.expected_delivery_date,
               po.status, po.total_amount_lkr, po.notes,
               COUNT(poi.purchase_order_item_id) AS item_count,
               COALESCE(SUM(poi.quantity - poi.received_quantity), 0) AS outstanding_quantity
        FROM purchase_orders po
        JOIN suppliers s USING (supplier_id)
        LEFT JOIN purchase_order_items poi USING (purchase_order_id)
        WHERE (:supplier_id = '' OR po.supplier_id = :supplier_id)
          AND (:status = '' OR po.status = :status)
          AND (:search = '' OR po.purchase_order_no ILIKE :pattern OR s.supplier_name ILIKE :pattern)
        GROUP BY po.purchase_order_id, s.supplier_name
        ORDER BY po.order_date DESC, po.purchase_order_no DESC
        """,
        {
            "supplier_id": supplier_id,
            "status": status,
            "search": normalized_search,
            "pattern": f"%{normalized_search}%",
        },
    )


def get_purchase_order_details(purchase_order_id: str = "", purchase_order_no: str = "") -> pd.DataFrame:
    return query_df(
        """
        SELECT po.purchase_order_id, po.purchase_order_no, po.supplier_id, s.supplier_name,
               po.order_date, po.expected_delivery_date, po.status, po.total_amount_lkr,
               po.notes, poi.product_id, p.sku, p.product_name, p.category,
               poi.quantity, poi.unit_price_lkr, poi.received_quantity,
               poi.line_total_lkr, (poi.quantity - poi.received_quantity) AS outstanding_quantity
        FROM purchase_orders po
        JOIN suppliers s USING (supplier_id)
        JOIN purchase_order_items poi USING (purchase_order_id)
        JOIN products p USING (product_id)
        WHERE (:purchase_order_id = '' OR po.purchase_order_id = :purchase_order_id)
          AND (:purchase_order_no = '' OR po.purchase_order_no = :purchase_order_no)
        ORDER BY p.product_name
        """,
        {"purchase_order_id": purchase_order_id, "purchase_order_no": purchase_order_no},
    )


def update_purchase_order_status(purchase_order_id: str, status: str) -> str:
    normalized_status = _validate_po_status(status)
    with transaction() as connection:
        row = connection.execute(
            text(
                "SELECT purchase_order_no, status FROM purchase_orders "
                "WHERE purchase_order_id=:purchase_order_id FOR UPDATE"
            ),
            {"purchase_order_id": purchase_order_id},
        ).mappings().first()
        if row is None:
            raise ValueError("The selected purchase order does not exist.")
        current_status = str(row["status"])
        if normalized_status == "Received":
            remaining = connection.execute(
                text(
                    "SELECT COALESCE(SUM(quantity - received_quantity), 0) "
                    "FROM purchase_order_items WHERE purchase_order_id=:purchase_order_id"
                ),
                {"purchase_order_id": purchase_order_id},
            ).scalar_one()
            if int(remaining) != 0:
                raise ValueError("A purchase order can be marked Received only when all quantities are received.")
        if normalized_status == "Partially Received":
            quantities = connection.execute(
                text(
                    "SELECT COALESCE(SUM(quantity), 0) AS ordered_quantity, "
                    "COALESCE(SUM(received_quantity), 0) AS received_quantity "
                    "FROM purchase_order_items WHERE purchase_order_id=:purchase_order_id"
                ),
                {"purchase_order_id": purchase_order_id},
            ).mappings().one()
            if int(quantities["received_quantity"]) == 0 or int(
                quantities["received_quantity"]
            ) >= int(quantities["ordered_quantity"]):
                raise ValueError("A purchase order must have both received and outstanding quantities to be Partially Received.")
        if normalized_status == "Ordered":
            received = connection.execute(
                text(
                    "SELECT COALESCE(SUM(received_quantity), 0) "
                    "FROM purchase_order_items WHERE purchase_order_id=:purchase_order_id"
                ),
                {"purchase_order_id": purchase_order_id},
            ).scalar_one()
            if int(received) != 0:
                raise ValueError("A purchase order with received quantities cannot return to Ordered status.")
        if normalized_status != current_status and normalized_status not in PO_STATUS_TRANSITIONS.get(
            current_status, set()
        ):
            raise ValueError(
                f"Cannot change purchase order status from {current_status} to {normalized_status}."
            )
        if normalized_status != current_status:
            connection.execute(
                text(
                    "UPDATE purchase_orders SET status=:status, updated_at=CURRENT_TIMESTAMP "
                    "WHERE purchase_order_id=:purchase_order_id"
                ),
                {"purchase_order_id": purchase_order_id, "status": normalized_status},
            )
        return str(row["purchase_order_no"])


def record_goods_receipt(
    purchase_order_id: str,
    warehouse_id: str,
    received_items: list[dict[str, Any]],
    received_date: date | None = None,
    notes: str = "",
) -> str:
    """Apply a goods receipt against a purchase order and update inventory and stock movements."""
    if not received_items:
        raise ValueError("At least one product must be marked as received.")
    received_date = received_date or date.today()
    with transaction() as connection:
        po = connection.execute(
            text(
                "SELECT purchase_order_id, purchase_order_no, supplier_id, status, total_amount_lkr "
                "FROM purchase_orders WHERE purchase_order_id=:purchase_order_id FOR UPDATE"
            ),
            {"purchase_order_id": purchase_order_id},
        ).mappings().first()
        if po is None:
            raise ValueError("Select an existing purchase order.")
        if po["status"] not in {"Ordered", "Partially Received"}:
            raise ValueError("Only Ordered or Partially Received purchase orders can receive goods.")
        if not _warehouse_exists(connection, warehouse_id):
            raise ValueError("Select an existing warehouse.")
        items = connection.execute(
            text(
                "SELECT purchase_order_item_id, product_id, quantity, unit_price_lkr, received_quantity "
                "FROM purchase_order_items WHERE purchase_order_id=:purchase_order_id "
                "ORDER BY product_id FOR UPDATE"
            ),
            {"purchase_order_id": purchase_order_id},
        ).mappings().all()
        item_by_product = {str(item["product_id"]): dict(item) for item in items}
        product_ids = [str(entry["product_id"]).strip() for entry in received_items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Each product can appear only once in a goods receipt.")
        receipt_no = _next_receipt_number()
        receipt_id = _new_id("GR")
        connection.execute(
            text(
                """
                INSERT INTO goods_received (
                    goods_received_id, purchase_order_id, receipt_no,
                    warehouse_id, received_date, notes, created_at
                )
                VALUES (:goods_received_id, :purchase_order_id, :receipt_no,
                    :warehouse_id, :received_date, :notes, CURRENT_TIMESTAMP)
                """
            ),
            {
                "goods_received_id": receipt_id,
                "purchase_order_id": purchase_order_id,
                "receipt_no": receipt_no,
                "warehouse_id": warehouse_id,
                "received_date": received_date,
                "notes": notes.strip(),
            },
        )
        total_received_quantity = 0
        for entry in received_items:
            product_id = str(entry["product_id"]).strip()
            received_quantity = whole_number(entry.get("quantity_received"), "Received quantity", minimum=1)
            if product_id not in item_by_product:
                raise ValueError(f"Product {product_id} is not on the selected purchase order.")
            item = item_by_product[product_id]
            outstanding_quantity = int(item["quantity"]) - int(item["received_quantity"])
            if received_quantity > outstanding_quantity:
                raise ValueError(
                    f"Received quantity exceeds outstanding quantity for product {product_id}."
                )
            unit_cost = nonnegative_money(
                entry.get("unit_cost_lkr", item["unit_price_lkr"]),
                "Received unit cost",
            )
            line_total = Decimal(received_quantity) * unit_cost
            item_receipt_id = _new_id("GRI")
            connection.execute(
                text(
                    """
                    INSERT INTO goods_received_items (
                        goods_received_item_id, goods_received_id,
                        purchase_order_item_id, product_id, quantity_received,
                        unit_cost_lkr, line_total_lkr
                    )
                    VALUES (:goods_received_item_id, :goods_received_id,
                        :purchase_order_item_id, :product_id, :quantity_received,
                        :unit_cost_lkr, :line_total_lkr)
                    """
                ),
                {
                    "goods_received_item_id": item_receipt_id,
                    "goods_received_id": receipt_id,
                    "purchase_order_item_id": item["purchase_order_item_id"],
                    "product_id": product_id,
                    "quantity_received": received_quantity,
                    "unit_cost_lkr": unit_cost,
                    "line_total_lkr": line_total,
                },
            )
            connection.execute(
                text(
                    "UPDATE purchase_order_items SET received_quantity = received_quantity + :delta "
                    "WHERE purchase_order_item_id=:purchase_order_item_id"
                ),
                {"delta": received_quantity, "purchase_order_item_id": item["purchase_order_item_id"]},
            )
            _ensure_inventory_for_receipt(connection, product_id, warehouse_id)
            connection.execute(
                text(
                    "UPDATE inventory SET quantity_on_hand=quantity_on_hand+:delta, "
                    "available_quantity=available_quantity+:delta, last_updated=:today "
                    "WHERE product_id=:product_id AND warehouse_id=:warehouse_id"
                ),
                {
                    "delta": received_quantity,
                    "product_id": product_id,
                    "warehouse_id": warehouse_id,
                    "today": received_date,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO stock_movements (
                        movement_id, movement_date, product_id, warehouse_id,
                        movement_type, quantity, reference_no, unit_cost_lkr, notes
                    )
                    VALUES (:movement_id, :movement_date, :product_id, :warehouse_id,
                        :movement_type, :quantity, :reference_no, :unit_cost_lkr, :notes)
                    """
                ),
                {
                    "movement_id": _new_id("MOV"),
                    "movement_date": received_date,
                    "product_id": product_id,
                    "warehouse_id": warehouse_id,
                    "movement_type": "RECEIPT",
                    "quantity": received_quantity,
                    "reference_no": po["purchase_order_no"],
                    "unit_cost_lkr": unit_cost,
                    "notes": f"Goods receipt via {receipt_no}",
                },
            )
            total_received_quantity += received_quantity
        remaining = connection.execute(
            text(
                "SELECT SUM(quantity - received_quantity) AS remaining_quantity "
                "FROM purchase_order_items WHERE purchase_order_id=:purchase_order_id"
            ),
            {"purchase_order_id": purchase_order_id},
        ).mappings().first()
        remaining_quantity = int(remaining["remaining_quantity"] or 0) if remaining else 0
        if remaining_quantity == 0:
            next_status = "Received"
        elif po["status"] == "Partially Received" or total_received_quantity > 0:
            next_status = "Partially Received"
        else:
            next_status = "Ordered"
        connection.execute(
            text("UPDATE purchase_orders SET status=:status, updated_at=CURRENT_TIMESTAMP WHERE purchase_order_id=:purchase_order_id"),
            {"status": next_status, "purchase_order_id": purchase_order_id},
        )
    return receipt_no


def procurement_recommendations(
    warehouse_id: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Rule-based replenishment recommendations based on stock, thresholds, and open purchase order quantities."""
    params: dict[str, Any] = {"warehouse_id": warehouse_id}
    date_filters: list[str] = []
    if start_date is not None:
        date_filters.append("i.last_updated >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        date_filters.append("i.last_updated <= :end_date")
        params["end_date"] = end_date
    date_filter_clause = "".join(f"\n          AND {condition}" for condition in date_filters)
    return query_df(
        f"""
        WITH outstanding AS (
            SELECT poi.product_id,
                   SUM(poi.quantity - poi.received_quantity) AS outstanding_quantity
            FROM purchase_order_items poi
            JOIN purchase_orders po USING (purchase_order_id)
            WHERE po.status NOT IN ('Cancelled', 'Received')
            GROUP BY poi.product_id
        )
        SELECT i.inventory_id, i.product_id, p.sku, p.product_name, p.category,
               i.warehouse_id, w.warehouse_name, i.quantity_on_hand,
               i.reorder_level, i.maximum_stock_level,
               COALESCE(o.outstanding_quantity, 0) AS outstanding_po_quantity,
               GREATEST(0, i.maximum_stock_level - i.quantity_on_hand - COALESCE(o.outstanding_quantity, 0))
                   AS recommended_replenishment,
               s.supplier_name, p.lead_time_days,
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
        LEFT JOIN outstanding o USING (product_id)
        WHERE (
            i.quantity_on_hand = 0
            OR (i.quantity_on_hand <= i.reorder_level AND i.quantity_on_hand > 0)
            OR i.quantity_on_hand > i.maximum_stock_level
        )
          AND (:warehouse_id = '' OR i.warehouse_id = :warehouse_id)
          {date_filter_clause}
        ORDER BY CASE WHEN i.quantity_on_hand = 0 THEN 0 ELSE 1 END,
                 i.quantity_on_hand, p.product_name
        """,
        params,
    )


def purchase_order_recommendations(
    warehouse_id: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    return procurement_recommendations(warehouse_id=warehouse_id, start_date=start_date, end_date=end_date)


def supplier_performance_dashboard() -> pd.DataFrame:
    return query_df(
        """
        WITH delivery_summary AS (
            SELECT po.supplier_id,
                   po.purchase_order_id,
                   po.total_amount_lkr,
                   po.order_date,
                   po.expected_delivery_date,
                   po.status,
                   MIN(gr.received_date) AS actual_delivery_date
            FROM purchase_orders po
            LEFT JOIN goods_received gr ON gr.purchase_order_id = po.purchase_order_id
            GROUP BY po.supplier_id, po.purchase_order_id, po.total_amount_lkr,
                     po.order_date, po.expected_delivery_date, po.status
        )
        SELECT s.supplier_id,
               s.supplier_name,
               COUNT(ds.purchase_order_id) AS total_purchase_orders,
               COALESCE(SUM(ds.total_amount_lkr), 0) AS total_purchase_value_lkr,
               COALESCE(AVG(ds.total_amount_lkr), 0) AS average_purchase_order_value_lkr,
               SUM(CASE WHEN ds.status = 'Received' THEN 1 ELSE 0 END) AS completed_orders,
               ROUND(
                   100.0 * AVG(
                       CASE
                           WHEN ds.expected_delivery_date IS NOT NULL
                            AND ds.actual_delivery_date IS NOT NULL
                            AND ds.actual_delivery_date <= ds.expected_delivery_date THEN 100.0
                           WHEN ds.expected_delivery_date IS NOT NULL
                            AND ds.actual_delivery_date IS NOT NULL THEN 0.0
                           ELSE NULL
                       END
                   ),
                   2
               ) AS on_time_delivery_pct,
               AVG(
                   CASE
                       WHEN ds.expected_delivery_date IS NOT NULL
                        AND ds.actual_delivery_date IS NOT NULL THEN
                           ds.actual_delivery_date - ds.expected_delivery_date
                       ELSE NULL
                   END
               ) AS average_delivery_delay_days,
               SUM(CASE
                     WHEN ds.status IN ('Draft', 'Pending Approval', 'Approved', 'Ordered', 'Partially Received')
                     THEN 1 ELSE 0
                   END) AS outstanding_orders
        FROM suppliers s
        LEFT JOIN delivery_summary ds ON ds.supplier_id = s.supplier_id
        GROUP BY s.supplier_id, s.supplier_name
        ORDER BY total_purchase_value_lkr DESC NULLS LAST
        """
    )


def procurement_spend_dashboard(
    start_date: date | None = None,
    end_date: date | None = None,
    supplier_id: str = "",
    category: str = "",
) -> dict[str, Any]:
    params: dict[str, Any] = {"supplier_id": supplier_id, "category": category}
    date_filters: list[str] = []
    if start_date is not None:
        date_filters.append("po.order_date >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        date_filters.append("po.order_date <= :end_date")
        params["end_date"] = end_date
    date_filter_clause = "".join(f"\n          AND {condition}" for condition in date_filters)
    monthly = query_df(
        f"""
        SELECT DATE_TRUNC('month', po.order_date)::date AS order_month,
               SUM(poi.line_total_lkr) AS procurement_expenditure_lkr,
               COUNT(DISTINCT po.purchase_order_id) AS purchase_orders
        FROM purchase_orders po
        JOIN purchase_order_items poi USING (purchase_order_id)
        JOIN products p USING (product_id)
        WHERE (:supplier_id = '' OR po.supplier_id = :supplier_id)
          AND (:category = '' OR p.category = :category)
          {date_filter_clause}
        GROUP BY DATE_TRUNC('month', po.order_date)::date
        ORDER BY order_month
        """,
        params,
    )
    by_supplier = query_df(
        f"""
        SELECT s.supplier_name, SUM(poi.line_total_lkr) AS procurement_expenditure_lkr,
               COUNT(DISTINCT po.purchase_order_id) AS purchase_orders
        FROM purchase_orders po
        JOIN purchase_order_items poi USING (purchase_order_id)
        JOIN products p USING (product_id)
        JOIN suppliers s USING (supplier_id)
        WHERE (:supplier_id = '' OR po.supplier_id = :supplier_id)
          AND (:category = '' OR p.category = :category)
          {date_filter_clause}
        GROUP BY s.supplier_name
        ORDER BY procurement_expenditure_lkr DESC
        """,
        params,
    )
    by_product = query_df(
        f"""
        SELECT p.product_name, p.category, SUM(poi.line_total_lkr) AS procurement_expenditure_lkr,
               SUM(poi.quantity) AS units_ordered
        FROM purchase_orders po
        JOIN purchase_order_items poi USING (purchase_order_id)
        JOIN products p USING (product_id)
        WHERE (:supplier_id = '' OR po.supplier_id = :supplier_id)
          AND (:category = '' OR p.category = :category)
          {date_filter_clause}
        GROUP BY p.product_name, p.category
        ORDER BY procurement_expenditure_lkr DESC
        """,
        params,
    )
    by_category = query_df(
        f"""
        SELECT p.category, SUM(poi.line_total_lkr) AS procurement_expenditure_lkr,
               COUNT(DISTINCT po.purchase_order_id) AS purchase_orders
        FROM purchase_orders po
        JOIN purchase_order_items poi USING (purchase_order_id)
        JOIN products p USING (product_id)
        WHERE (:supplier_id = '' OR po.supplier_id = :supplier_id)
          AND (:category = '' OR p.category = :category)
          {date_filter_clause}
        GROUP BY p.category
        ORDER BY procurement_expenditure_lkr DESC
        """,
        params,
    )
    summary = query_df(
        f"""
        SELECT COALESCE(SUM(poi.line_total_lkr), 0) AS total_procurement_expenditure_lkr,
               COUNT(DISTINCT po.purchase_order_id) AS total_purchase_orders
        FROM purchase_orders po
        JOIN purchase_order_items poi USING (purchase_order_id)
        JOIN products p USING (product_id)
        WHERE (:supplier_id = '' OR po.supplier_id = :supplier_id)
          AND (:category = '' OR p.category = :category)
          {date_filter_clause}
        """,
        params,
    )
    return {
        "summary": summary,
        "monthly": monthly,
        "by_supplier": by_supplier,
        "by_product": by_product,
        "by_category": by_category,
        "trend": monthly,
    }


def supplier_performance_summary() -> pd.DataFrame:
    return supplier_performance_dashboard()


def procurement_spend_summary(
    start_date: date | None = None,
    end_date: date | None = None,
    supplier_id: str = "",
    category: str = "",
) -> pd.DataFrame:
    return procurement_spend_dashboard(start_date, end_date, supplier_id, category)["monthly"]
