from __future__ import annotations

import argparse
import json
from pathlib import Path

from receipt_matcher import expense_from_dict, match_receipt, receipt_from_dict


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "sample_data.json"
OUTPUT = ROOT / "demo_output.json"


def _require_unique(items: list, attribute: str, label: str) -> None:
    values = [getattr(item, attribute) for item in items]
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique within one input batch")


def run(input_path: Path = INPUT, output_path: Path = OUTPUT) -> dict:
    """Evaluate one synthetic batch and write a deterministic JSON report."""

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data.get("receipts"), list) or not isinstance(
        data.get("expenses"), list
    ):
        raise ValueError("input must contain receipts and expenses arrays")

    receipts = [receipt_from_dict(item) for item in data["receipts"]]
    expenses = [expense_from_dict(item) for item in data["expenses"]]
    _require_unique(receipts, "receipt_id", "receipt IDs")
    _require_unique(expenses, "expense_id", "expense IDs")
    decisions = [
        match_receipt(receipt, expenses).to_dict()
        for receipt in receipts
    ]

    receipt_lookup = {item["receipt_id"]: item for item in data["receipts"]}
    for decision in decisions:
        decision["receipt"] = receipt_lookup[decision["receipt_id"]]

    result = {
        "generated_from": "Synthetic portfolio data only",
        "decision_policy": {
            "date_window_days": 5,
            "amount_tolerance": "0.01",
            "auto_match_threshold": 0.84,
            "ambiguity_margin": 0.12,
        },
        "summary": {
            "receipts": len(decisions),
            "auto_matched": sum(item["status"] == "auto_match" for item in decisions),
            "manual_review": sum(item["status"].startswith("manual_review") for item in decisions),
        },
        "decisions": decisions,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the credential-free receipt matching demonstration."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT,
        help="JSON input containing synthetic receipts and expenses.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT,
        help="Destination for the generated decision report.",
    )
    args = parser.parse_args()

    output = run(args.input, args.output)
    print(json.dumps(output["summary"], indent=2))
    print(f"Wrote {args.output.resolve()}")


if __name__ == "__main__":
    main()
