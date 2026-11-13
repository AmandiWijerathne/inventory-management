"""Database-driven KPI and chart datasets for the dashboard."""

from __future__ import annotations

import pandas as pd

from backend.database import query_df


def dashboard_kpis() -> dict[str, float | int]:
    row = query_df(
        """
        SELECT (SELECT COUNT(*) FROM products) AS total_products,
               COALESCE(SUM(i.quantity_on_hand), 0)::BIGINT AS total_inventory_quantity,
               COALESCE(SUM(i.quantity_on_hand * p.unit_cost_lkr), 0)::NUMERIC(18, 2)
                   AS total_inventory_value_lkr,
               (SELECT COUNT(*) FROM warehouses) AS total_warehouses,
               COUNT(*) FILTER (WHERE i.quantity_on_hand > 0
                                AND i.quantity_on_hand <= i.reorder_level) AS low_stock_items,
               COUNT(*) FILTER (WHERE i.quantity_on_hand = 0) AS out_of_stock_items
        FROM inventory i JOIN products p USING (product_id)
        """
    ).iloc[0].to_dict()
    return row


def category_value() -> pd.DataFrame:
    return query_df(
        """
        SELECT p.category, SUM(i.quantity_on_hand * p.unit_cost_lkr) AS inventory_value_lkr
        FROM inventory i JOIN products p USING (product_id)
        GROUP BY p.category ORDER BY inventory_value_lkr DESC
        """
    )


def warehouse_stock_distribution() -> pd.DataFrame:
    return query_df(
        """
        SELECT w.warehouse_name, SUM(i.quantity_on_hand)::BIGINT AS stock_units,
               SUM(i.quantity_on_hand * p.unit_cost_lkr) AS inventory_value_lkr
        FROM warehouses w JOIN inventory i USING (warehouse_id)
        JOIN products p USING (product_id)
        GROUP BY w.warehouse_id ORDER BY stock_units DESC
        """
    )


def monthly_receipts_issues() -> pd.DataFrame:
    return query_df(
        """
        SELECT date_trunc('month', movement_date)::DATE AS month,
               COALESCE(SUM(quantity) FILTER (WHERE movement_type = 'RECEIPT'), 0)::BIGINT
                   AS receipts,
               COALESCE(SUM(quantity) FILTER (WHERE movement_type = 'ISSUE'), 0)::BIGINT
                   AS issues
        FROM stock_movements
        GROUP BY date_trunc('month', movement_date)
        ORDER BY month
        """
    )


def status_distribution() -> pd.DataFrame:
    return query_df(
        """
        SELECT CASE WHEN i.quantity_on_hand=0 THEN 'Out of Stock'
                    WHEN i.quantity_on_hand>i.maximum_stock_level THEN 'Overstock'
                    WHEN i.quantity_on_hand<=i.reorder_level THEN 'Low Stock'
                    ELSE 'In Stock' END AS inventory_status,
               COUNT(*) AS item_locations
        FROM inventory i
        GROUP BY inventory_status
        ORDER BY item_locations DESC
        """
    )


def top_products_by_value() -> pd.DataFrame:
    return query_df(
        """
        SELECT p.product_name, p.sku,
               SUM(i.quantity_on_hand * p.unit_cost_lkr) AS inventory_value_lkr
        FROM inventory i JOIN products p USING (product_id)
        GROUP BY p.product_id ORDER BY inventory_value_lkr DESC LIMIT 10
        """
    )
