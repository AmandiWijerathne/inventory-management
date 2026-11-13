import unittest
from collections import Counter, defaultdict
from pathlib import Path

from database.import_data import load_and_validate_dataset


class DatasetValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tables = load_and_validate_dataset()

    def test_expected_source_row_counts_are_preserved(self) -> None:
        self.assertEqual(len(self.tables["products"]), 59)
        self.assertEqual(len(self.tables["warehouses"]), 5)
        self.assertEqual(len(self.tables["suppliers"]), 12)
        self.assertEqual(len(self.tables["inventory"]), 295)
        self.assertEqual(len(self.tables["stock_movements"]), 1713)

    def test_foreign_keys_and_product_warehouse_pairs_are_valid(self) -> None:
        suppliers = {row["supplier_id"] for row in self.tables["suppliers"]}
        products = {row["product_id"] for row in self.tables["products"]}
        warehouses = {row["warehouse_id"] for row in self.tables["warehouses"]}
        self.assertTrue(all(row["supplier_id"] in suppliers for row in self.tables["products"]))
        self.assertTrue(all(
            row["product_id"] in products and row["warehouse_id"] in warehouses
            for row in self.tables["inventory"]
        ))
        pairs = [(row["product_id"], row["warehouse_id"]) for row in self.tables["inventory"]]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_current_quantities_reconcile_with_signed_movements(self) -> None:
        signed = defaultdict(int)
        for row in self.tables["stock_movements"]:
            amount = row["quantity"] if row["movement_type"] in {
                "RECEIPT", "TRANSFER_IN", "ADJUSTMENT_IN"
            } else -row["quantity"]
            signed[(row["product_id"], row["warehouse_id"])] += amount
        for inventory in self.tables["inventory"]:
            self.assertEqual(
                inventory["opening_quantity"] + signed[
                    (inventory["product_id"], inventory["warehouse_id"])
                ],
                inventory["quantity_on_hand"],
                inventory["inventory_id"],
            )

    def test_transfer_references_have_balanced_pairs(self) -> None:
        transfers = defaultdict(list)
        for row in self.tables["stock_movements"]:
            if row["movement_type"] in {"TRANSFER_IN", "TRANSFER_OUT"}:
                transfers[row["reference_no"]].append(row)
        self.assertEqual(len(transfers), 100)
        for reference, rows in transfers.items():
            self.assertEqual(Counter(row["movement_type"] for row in rows),
                             Counter({"TRANSFER_IN": 1, "TRANSFER_OUT": 1}), reference)
            self.assertEqual(
                {(row["product_id"], row["quantity"]) for row in rows},
                {(rows[0]["product_id"], rows[0]["quantity"])},
                reference,
            )


if __name__ == "__main__":
    unittest.main()
