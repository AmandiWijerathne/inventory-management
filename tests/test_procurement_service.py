import unittest
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pandas as pd

from backend.procurement_service import (
    create_purchase_order,
    procurement_recommendations,
    procurement_spend_dashboard,
    record_goods_receipt,
    update_purchase_order_status,
)


class _MappingRows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def one(self):
        return self.rows[0]


class _Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = _MappingRows(rows)
        self.scalar = scalar

    def mappings(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class _Connection:
    def __init__(self, execute):
        self.execute_statement = execute
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params or {}))
        return self.execute_statement(sql, params or {})


class ProcurementRecommendationQueryTests(unittest.TestCase):
    @patch("backend.procurement_service.query_df", return_value=pd.DataFrame())
    def test_missing_dates_are_omitted_from_query_parameters(self, query_df) -> None:
        procurement_recommendations()
        query = query_df.call_args.args[0]
        params = query_df.call_args.args[1]
        self.assertNotIn(":start_date", query)
        self.assertNotIn(":end_date", query)
        self.assertNotIn("start_date", params)
        self.assertNotIn("end_date", params)

    @patch("backend.procurement_service.query_df", return_value=pd.DataFrame())
    def test_supplied_date_filters_are_included(self, query_df) -> None:
        procurement_recommendations(start_date=date(2026, 1, 1), end_date=date(2026, 11, 11))
        query = query_df.call_args.args[0]
        params = query_df.call_args.args[1]
        self.assertIn("i.last_updated >= :start_date", query)
        self.assertIn("i.last_updated <= :end_date", query)
        self.assertEqual(params["start_date"], date(2026, 1, 1))
        self.assertEqual(params["end_date"], date(2026, 11, 11))

    @patch("backend.procurement_service.query_df", return_value=pd.DataFrame())
    def test_spend_dashboard_applies_dates_to_every_query(self, query_df) -> None:
        start = date(2026, 1, 1)
        end = date(2026, 11, 11)

        procurement_spend_dashboard(start_date=start, end_date=end)

        self.assertEqual(query_df.call_count, 5)
        for call in query_df.call_args_list:
            query, params = call.args
            self.assertIn("po.order_date >= :start_date", query)
            self.assertIn("po.order_date <= :end_date", query)
            self.assertEqual(params["start_date"], start)
            self.assertEqual(params["end_date"], end)

    @patch("backend.procurement_service.query_df", return_value=pd.DataFrame())
    def test_spend_dashboard_omits_unsupplied_date_filters(self, query_df) -> None:
        procurement_spend_dashboard()

        for call in query_df.call_args_list:
            query, params = call.args
            self.assertNotIn(":start_date", query)
            self.assertNotIn(":end_date", query)
            self.assertNotIn("start_date", params)
            self.assertNotIn("end_date", params)

    @patch("backend.procurement_service.query_df", return_value=pd.DataFrame())
    def test_supplier_spend_joins_supplier_to_purchase_order_explicitly(self, query_df) -> None:
        procurement_spend_dashboard()

        supplier_query = query_df.call_args_list[1].args[0]
        self.assertIn("JOIN suppliers s ON s.supplier_id = po.supplier_id", supplier_query)
        self.assertNotIn("JOIN suppliers s USING (supplier_id)", supplier_query)

    def test_create_purchase_order_inserts_parent_before_items(self) -> None:
        connection = _Connection(
            lambda sql, params: _Result([{
                "product_id": "P1",
                "product_name": "Widget",
                "supplier_id": "S1",
                "unit_cost_lkr": Decimal("12.50"),
            }]) if "FROM products" in sql else _Result()
        )
        with (
            patch("backend.procurement_service.transaction", return_value=nullcontext(connection)),
            patch("backend.procurement_service._supplier_exists", return_value=True),
        ):
            create_purchase_order(
                supplier_id="S1",
                items=[{"product_id": "P1", "quantity": 3, "unit_price_lkr": 10}],
            )

        inserted_tables = [
            sql.split("INSERT INTO ", 1)[1].split(" ", 1)[0]
            for sql, _ in connection.statements
            if "INSERT INTO " in sql
        ]
        self.assertEqual(inserted_tables, ["purchase_orders", "purchase_order_items"])
        product_query = next(
            sql for sql, _ in connection.statements if "FROM products" in sql
        )
        self.assertIn("unit_cost_lkr FROM products", product_query)

    def test_receipt_locks_order_and_items_and_updates_inventory_and_movement(self) -> None:
        item = {
            "purchase_order_item_id": "POI1",
            "product_id": "P1",
            "quantity": 5,
            "unit_price_lkr": Decimal("10.00"),
            "received_quantity": 0,
        }

        def execute(sql, _params):
            if "FROM purchase_orders" in sql and "SELECT" in sql:
                return _Result([{
                    "purchase_order_id": "PO1",
                    "purchase_order_no": "PO-1",
                    "supplier_id": "S1",
                    "status": "Ordered",
                    "total_amount_lkr": Decimal("50.00"),
                }])
            if "SELECT purchase_order_item_id" in sql:
                return _Result([item])
            if "SUM(quantity - received_quantity)" in sql:
                return _Result([{"remaining_quantity": 3}])
            return _Result()

        connection = _Connection(execute)
        with (
            patch("backend.procurement_service.transaction", return_value=nullcontext(connection)),
            patch("backend.procurement_service._warehouse_exists", return_value=True),
            patch("backend.procurement_service._ensure_inventory_for_receipt"),
        ):
            record_goods_receipt(
                "PO1", "W1", [{"product_id": "P1", "quantity_received": 2}]
            )

        order_lock = next(sql for sql, _ in connection.statements if "FROM purchase_orders" in sql)
        item_lock = next(sql for sql, _ in connection.statements if "SELECT purchase_order_item_id" in sql)
        self.assertIn("FOR UPDATE", order_lock)
        self.assertIn("FOR UPDATE", item_lock)
        inventory_update = next(
            params for sql, params in connection.statements if "UPDATE inventory SET" in sql
        )
        self.assertEqual(inventory_update["delta"], 2)
        movement = next(
            params for sql, params in connection.statements if "INSERT INTO stock_movements" in sql
        )
        self.assertEqual(movement["movement_type"], "RECEIPT")
        self.assertEqual(movement["quantity"], 2)
        self.assertEqual(movement["reference_no"], "PO-1")

    def test_receipt_rejects_duplicate_products_in_one_submission(self) -> None:
        item = {
            "purchase_order_item_id": "POI1",
            "product_id": "P1",
            "quantity": 5,
            "unit_price_lkr": Decimal("10.00"),
            "received_quantity": 0,
        }

        def execute(sql, _params):
            if "FROM purchase_orders" in sql:
                return _Result([{
                    "purchase_order_id": "PO1",
                    "purchase_order_no": "PO-1",
                    "supplier_id": "S1",
                    "status": "Ordered",
                    "total_amount_lkr": Decimal("50.00"),
                }])
            if "SELECT purchase_order_item_id" in sql:
                return _Result([item])
            return _Result()

        connection = _Connection(execute)
        with (
            patch("backend.procurement_service.transaction", return_value=nullcontext(connection)),
            patch("backend.procurement_service._warehouse_exists", return_value=True),
            self.assertRaisesRegex(ValueError, "only once"),
        ):
            record_goods_receipt(
                "PO1",
                "W1",
                [
                    {"product_id": "P1", "quantity_received": 2},
                    {"product_id": "P1", "quantity_received": 2},
                ],
            )

        self.assertFalse(any("INSERT INTO goods_received" in sql for sql, _ in connection.statements))

    def test_received_status_is_rejected_with_outstanding_quantities(self) -> None:
        def execute(sql, _params):
            if "FROM purchase_orders" in sql:
                return _Result([{"purchase_order_no": "PO-1", "status": "Ordered"}])
            if "SUM(quantity - received_quantity)" in sql:
                return _Result(scalar=1)
            return _Result()

        connection = _Connection(execute)
        with (
            patch("backend.procurement_service.transaction", return_value=nullcontext(connection)),
            self.assertRaisesRegex(ValueError, "all quantities are received"),
        ):
            update_purchase_order_status("PO1", "Received")

        self.assertTrue(any("FOR UPDATE" in sql for sql, _ in connection.statements))
        self.assertFalse(any("UPDATE purchase_orders" in sql for sql, _ in connection.statements))

    def test_invalid_purchase_order_transition_is_rejected(self) -> None:
        def execute(sql, _params):
            if "FROM purchase_orders" in sql:
                return _Result([{"purchase_order_no": "PO-1", "status": "Draft"}])
            if "SUM(received_quantity)" in sql:
                return _Result(scalar=0)
            return _Result()

        connection = _Connection(execute)
        with (
            patch("backend.procurement_service.transaction", return_value=nullcontext(connection)),
            self.assertRaisesRegex(ValueError, "Cannot change purchase order status"),
        ):
            update_purchase_order_status("PO1", "Ordered")

        self.assertFalse(any("UPDATE purchase_orders" in sql for sql, _ in connection.statements))


if __name__ == "__main__":
    unittest.main()
