from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from receipt_matcher import (
    Expense,
    MatchConfig,
    Receipt,
    dropbox_folder_for,
    idempotency_key,
    match_receipt,
)
from run_demo import INPUT, run


def receipt(**overrides):
    values = {
        "receipt_id": "R-1",
        "message_id": "<message-1@example.test>",
        "attachment_sha256": "a" * 64,
        "expense_date": date(2026, 7, 15),
        "amount": Decimal("86.40"),
        "currency": "USD",
        "client_alias": "Northwind Retail",
        "freshbooks_client_id": "FB-101",
    }
    values.update(overrides)
    return Receipt(**values)


class ReceiptMatcherTests(unittest.TestCase):
    def test_unique_candidate_auto_matches(self):
        expenses = [
            Expense("E-1", date(2026, 7, 14), Decimal("86.40"), "USD"),
            Expense("E-2", date(2026, 7, 15), Decimal("24.00"), "USD"),
        ]
        decision = match_receipt(receipt(), expenses)
        self.assertEqual(decision.status, "auto_match")
        self.assertEqual(decision.matched_expense_id, "E-1")

    def test_two_nearby_candidates_require_review(self):
        expenses = [
            Expense("E-1", date(2026, 7, 15), Decimal("86.40"), "USD"),
            Expense("E-2", date(2026, 7, 14), Decimal("86.40"), "USD"),
        ]
        decision = match_receipt(receipt(), expenses)
        self.assertEqual(decision.status, "manual_review_ambiguous")
        self.assertIsNone(decision.matched_expense_id)

    def test_attached_expense_is_never_reused(self):
        expenses = [
            Expense(
                "E-1",
                date(2026, 7, 15),
                Decimal("86.40"),
                "USD",
                has_attachment=True,
            )
        ]
        decision = match_receipt(receipt(), expenses)
        self.assertEqual(decision.status, "manual_review_no_match")

    def test_wrong_client_is_excluded(self):
        expenses = [
            Expense(
                "E-1",
                date(2026, 7, 15),
                Decimal("86.40"),
                "USD",
                client_id="FB-999",
            )
        ]
        decision = match_receipt(receipt(), expenses)
        self.assertEqual(decision.status, "manual_review_no_match")

    def test_low_confidence_candidate_requires_review(self):
        expenses = [
            Expense("E-1", date(2026, 7, 10), Decimal("86.40"), "USD"),
        ]
        decision = match_receipt(receipt(), expenses)
        self.assertEqual(decision.status, "manual_review_low_confidence")
        self.assertIsNone(decision.matched_expense_id)

    def test_idempotency_key_is_stable_and_normalized(self):
        first = idempotency_key(" <MESSAGE-1@EXAMPLE.TEST> ", "AA11")
        second = idempotency_key("<message-1@example.test>", "aa11")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_dropbox_folder_matches_requested_format(self):
        self.assertEqual(
            dropbox_folder_for(date(2026, 7, 15)),
            "/2026 Expenses/07 July/",
        )

    def test_invalid_attachment_hash_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly 64 hexadecimal"):
            receipt(attachment_sha256="not-a-sha256")

    def test_invalid_match_config_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            MatchConfig(date_window_days=-1)

    def test_sample_batch_is_valid_and_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "result.json"
            first = run(INPUT, output_path)
            second = run(INPUT, output_path)

            self.assertEqual(first, second)
            self.assertEqual(first["summary"], {
                "receipts": 5,
                "auto_matched": 2,
                "manual_review": 3,
            })
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8")),
                first,
            )

    def test_duplicate_receipt_ids_are_rejected(self):
        data = json.loads(INPUT.read_text(encoding="utf-8"))
        data["receipts"].append(data["receipts"][0].copy())

        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "duplicate.json"
            output_path = Path(directory) / "result.json"
            input_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "receipt IDs must be unique"):
                run(input_path, output_path)


if __name__ == "__main__":
    unittest.main()
