"""Deterministic receipt-to-expense matching for the portfolio demo.

The module deliberately contains no FreshBooks credentials or network calls. It
models the decision layer that can be used inside Make.com or behind a small API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
import re
from typing import Iterable


SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_positive_amount(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{field_name} must be a positive finite Decimal")


def _require_currency(value: str) -> None:
    if not isinstance(value, str) or CURRENCY_PATTERN.fullmatch(value) is None:
        raise ValueError("currency must be a three-letter alphabetic code")


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    message_id: str
    attachment_sha256: str
    expense_date: date
    amount: Decimal
    currency: str
    client_alias: str
    freshbooks_client_id: str

    def __post_init__(self) -> None:
        _require_text(self.receipt_id, "receipt_id")
        _require_text(self.message_id, "message_id")
        _require_text(self.client_alias, "client_alias")
        _require_text(self.freshbooks_client_id, "freshbooks_client_id")
        _require_positive_amount(self.amount, "amount")
        _require_currency(self.currency)
        if (
            not isinstance(self.attachment_sha256, str)
            or SHA256_PATTERN.fullmatch(self.attachment_sha256) is None
        ):
            raise ValueError("attachment_sha256 must contain exactly 64 hexadecimal characters")


@dataclass(frozen=True)
class Expense:
    expense_id: str
    expense_date: date
    amount: Decimal
    currency: str
    client_id: str | None = None
    has_attachment: bool = False

    def __post_init__(self) -> None:
        _require_text(self.expense_id, "expense_id")
        _require_positive_amount(self.amount, "amount")
        _require_currency(self.currency)
        if self.client_id is not None:
            _require_text(self.client_id, "client_id")


@dataclass(frozen=True)
class CandidateScore:
    expense_id: str
    score: float
    days_apart: int
    amount_delta: str
    client_state: str


@dataclass(frozen=True)
class MatchDecision:
    receipt_id: str
    status: str
    matched_expense_id: str | None
    confidence: float
    reasons: tuple[str, ...]
    candidates: tuple[CandidateScore, ...]
    idempotency_key: str
    dropbox_folder: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["candidates"] = [asdict(item) for item in self.candidates]
        return payload


@dataclass(frozen=True)
class MatchConfig:
    date_window_days: int = 5
    amount_tolerance: Decimal = Decimal("0.01")
    auto_match_threshold: float = 0.84
    ambiguity_margin: float = 0.12

    def __post_init__(self) -> None:
        if self.date_window_days < 0:
            raise ValueError("date_window_days cannot be negative")
        if not self.amount_tolerance.is_finite() or self.amount_tolerance < 0:
            raise ValueError("amount_tolerance must be a non-negative finite Decimal")
        if not 0 <= self.auto_match_threshold <= 1:
            raise ValueError("auto_match_threshold must be between 0 and 1")
        if not 0 <= self.ambiguity_margin <= 1:
            raise ValueError("ambiguity_margin must be between 0 and 1")


MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def dropbox_folder_for(expense_date: date) -> str:
    """Return the requested date-based Dropbox folder."""

    return (
        f"/{expense_date.year} Expenses/"
        f"{expense_date.month:02d} {MONTHS[expense_date.month - 1]}/"
    )


def idempotency_key(message_id: str, attachment_sha256: str) -> str:
    """Create a stable key for one Gmail attachment ingestion event."""

    _require_text(message_id, "message_id")
    _require_text(attachment_sha256, "attachment_sha256")
    normalized = f"{message_id.strip().lower()}:{attachment_sha256.strip().lower()}"
    return sha256(normalized.encode("utf-8")).hexdigest()


def _candidate_score(
    receipt: Receipt,
    expense: Expense,
    config: MatchConfig,
) -> CandidateScore | None:
    if expense.has_attachment:
        return None
    if receipt.currency.upper() != expense.currency.upper():
        return None

    days_apart = abs((receipt.expense_date - expense.expense_date).days)
    if days_apart > config.date_window_days:
        return None

    amount_delta = abs(receipt.amount - expense.amount)
    if amount_delta > config.amount_tolerance:
        return None

    amount_score = 0.68 * max(
        0.0,
        1.0 - float(amount_delta / (config.amount_tolerance + Decimal("0.01"))),
    )
    date_score = 0.27 * (1.0 - days_apart / (config.date_window_days + 1))

    if expense.client_id == receipt.freshbooks_client_id:
        client_score = 0.05
        client_state = "same client"
    elif expense.client_id is None:
        client_score = 0.03
        client_state = "client unset"
    else:
        return None

    return CandidateScore(
        expense_id=expense.expense_id,
        score=round(amount_score + date_score + client_score, 3),
        days_apart=days_apart,
        amount_delta=f"{amount_delta:.2f}",
        client_state=client_state,
    )


def match_receipt(
    receipt: Receipt,
    expenses: Iterable[Expense],
    config: MatchConfig | None = None,
) -> MatchDecision:
    """Match only when one candidate is confidently better than the rest."""

    config = config or MatchConfig()
    candidates = sorted(
        (
            score
            for expense in expenses
            if (score := _candidate_score(receipt, expense, config)) is not None
        ),
        key=lambda item: (-item.score, item.days_apart, item.expense_id),
    )

    base = {
        "receipt_id": receipt.receipt_id,
        "idempotency_key": idempotency_key(receipt.message_id, receipt.attachment_sha256),
        "dropbox_folder": dropbox_folder_for(receipt.expense_date),
    }

    if not candidates:
        return MatchDecision(
            **base,
            status="manual_review_no_match",
            matched_expense_id=None,
            confidence=0.0,
            reasons=(
                "No unattached expense passed currency, amount, client, and date gates.",
                "Preserve the receipt and extracted fields for manual review; do not create a duplicate expense.",
            ),
            candidates=(),
        )

    top = candidates[0]
    if top.score < config.auto_match_threshold:
        return MatchDecision(
            **base,
            status="manual_review_low_confidence",
            matched_expense_id=None,
            confidence=top.score,
            reasons=(
                f"Best candidate {top.expense_id} scored below the auto-match threshold.",
                "A human should confirm the expense before any attachment or client update.",
            ),
            candidates=tuple(candidates),
        )

    if len(candidates) > 1 and top.score - candidates[1].score < config.ambiguity_margin:
        return MatchDecision(
            **base,
            status="manual_review_ambiguous",
            matched_expense_id=None,
            confidence=top.score,
            reasons=(
                f"Top candidates are separated by only {top.score - candidates[1].score:.3f}.",
                "The workflow must not guess when two bank-feed expenses are plausible.",
            ),
            candidates=tuple(candidates),
        )

    return MatchDecision(
        **base,
        status="auto_match",
        matched_expense_id=top.expense_id,
        confidence=top.score,
        reasons=(
            "One unattached expense passed every deterministic gate.",
            "The next action may upload the receipt and update that existing expense with the mapped client.",
        ),
        candidates=tuple(candidates),
    )


def receipt_from_dict(payload: dict) -> Receipt:
    return Receipt(
        receipt_id=payload["receipt_id"],
        message_id=payload["message_id"],
        attachment_sha256=payload["attachment_sha256"],
        expense_date=date.fromisoformat(payload["expense_date"]),
        amount=Decimal(payload["amount"]),
        currency=payload["currency"],
        client_alias=payload["client_alias"],
        freshbooks_client_id=payload["freshbooks_client_id"],
    )


def expense_from_dict(payload: dict) -> Expense:
    return Expense(
        expense_id=payload["expense_id"],
        expense_date=date.fromisoformat(payload["expense_date"]),
        amount=Decimal(payload["amount"]),
        currency=payload["currency"],
        client_id=payload.get("client_id"),
        has_attachment=bool(payload.get("has_attachment", False)),
    )
