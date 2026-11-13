import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from backend.inventory_service import inventory_alerts


class InventoryAlertQueryTests(unittest.TestCase):
    @patch("backend.inventory_service.query_df", return_value=pd.DataFrame())
    def test_omitted_dates_are_not_sent_as_null_parameters(self, query_df) -> None:
        inventory_alerts()
        query = query_df.call_args.args[0]
        params = query_df.call_args.args[1]
        self.assertNotIn(":start_date", query)
        self.assertNotIn(":end_date", query)
        self.assertNotIn("start_date", params)
        self.assertNotIn("end_date", params)

    @patch("backend.inventory_service.query_df", return_value=pd.DataFrame())
    def test_date_filters_are_included_when_supplied(self, query_df) -> None:
        start = date(2026, 1, 1)
        end = date(2026, 11, 11)
        inventory_alerts(start_date=start, end_date=end)
        query = query_df.call_args.args[0]
        params = query_df.call_args.args[1]
        self.assertIn("i.last_updated >= :start_date", query)
        self.assertIn("i.last_updated <= :end_date", query)
        self.assertEqual(params["start_date"], start)
        self.assertEqual(params["end_date"], end)


if __name__ == "__main__":
    unittest.main()
