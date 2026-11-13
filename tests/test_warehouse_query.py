import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from backend.warehouse_service import warehouse_summary


class WarehouseSummaryQueryTests(unittest.TestCase):
    @patch("backend.warehouse_service.query_df", return_value=pd.DataFrame())
    def test_missing_dates_are_omitted_from_sql_and_parameters(self, query_df) -> None:
        warehouse_summary()
        query = query_df.call_args.args[0]
        params = query_df.call_args.args[1]
        self.assertNotIn(":start_date", query)
        self.assertNotIn(":end_date", query)
        self.assertNotIn("start_date", params)
        self.assertNotIn("end_date", params)

    @patch("backend.warehouse_service.query_df", return_value=pd.DataFrame())
    def test_date_filters_are_added_when_provided(self, query_df) -> None:
        start = date(2026, 1, 1)
        end = date(2026, 11, 11)
        warehouse_summary(start_date=start, end_date=end)
        query = query_df.call_args.args[0]
        params = query_df.call_args.args[1]
        self.assertIn("i.last_updated >= :start_date", query)
        self.assertIn("i.last_updated <= :end_date", query)
        self.assertEqual(params["start_date"], start)
        self.assertEqual(params["end_date"], end)


if __name__ == "__main__":
    unittest.main()
