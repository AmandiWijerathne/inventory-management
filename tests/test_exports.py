import unittest

import pandas as pd

from backend.report_service import to_csv_bytes, to_excel_bytes
from backend.validation import whole_number


class ReportExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = pd.DataFrame({
            "product": ["Router", "Office chair"],
            "inventory_value_lkr": [28500, 17500],
        })

    def test_csv_export_contains_headers_and_rows(self) -> None:
        exported = to_csv_bytes(self.frame)
        decoded = exported.decode("utf-8-sig")
        self.assertIn("product,inventory_value_lkr", decoded)
        self.assertIn("Router,28500", decoded)

    def test_excel_export_is_a_valid_workbook(self) -> None:
        exported = to_excel_bytes({"Inventory": self.frame})
        reopened = pd.read_excel(__import__("io").BytesIO(exported), sheet_name="Inventory")
        pd.testing.assert_frame_equal(reopened, self.frame)

    def test_spreadsheet_exports_escape_formula_like_text(self) -> None:
        unsafe = pd.DataFrame({"name": ["=1+1", "Normal"]})
        self.assertIn("'=1+1", to_csv_bytes(unsafe).decode("utf-8-sig"))
        reopened = pd.read_excel(
            __import__("io").BytesIO(to_excel_bytes({"Data": unsafe})), sheet_name="Data"
        )
        self.assertEqual(reopened.loc[0, "name"], "'=1+1")

    def test_whole_number_validation_rejects_fractional_and_negative_values(self) -> None:
        self.assertEqual(whole_number("12", "Quantity", minimum=1), 12)
        for invalid in ("1.5", "-1", "NaN"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    whole_number(invalid, "Quantity", minimum=1)


if __name__ == "__main__":
    unittest.main()
