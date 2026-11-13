import unittest
from unittest.mock import patch

import pandas as pd

from backend.stock_movement_service import movement_history


class MovementHistoryQueryTests(unittest.TestCase):
    @patch("backend.stock_movement_service.query_df", return_value=pd.DataFrame())
    def test_omitted_dates_do_not_add_untyped_null_parameters(self, query_df) -> None:
        movement_history(limit=12)
        query = query_df.call_args.args[0]
        params = query_df.call_args.args[1]
        self.assertNotIn(":start_date", query)
        self.assertNotIn(":end_date", query)
        self.assertNotIn("start_date", params)
        self.assertNotIn("end_date", params)
        self.assertIn("LIMIT :limit", query)
        self.assertEqual(params["limit"], 12)

    @patch("backend.stock_movement_service.query_df", return_value=pd.DataFrame())
    def test_supplied_date_filters_are_parameterized(self, query_df) -> None:
        from datetime import date

        start = date(2026, 1, 1)
        end = date(2026, 11, 11)
        movement_history(start_date=start, end_date=end)
        query = query_df.call_args.args[0]
        params = query_df.call_args.args[1]
        self.assertIn("m.movement_date >= :start_date", query)
        self.assertIn("m.movement_date <= :end_date", query)
        self.assertEqual(params["start_date"], start)
        self.assertEqual(params["end_date"], end)


if __name__ == "__main__":
    unittest.main()
