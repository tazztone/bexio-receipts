from typing import Any

from .config import Settings
from .database import DuplicateDetector
from .models import Receipt


class ReviewViewModel:
    def __init__(
        self,
        receipt: Receipt,
        all_accounts: list[dict[str, Any]],
        settings: Settings,
        db: DuplicateDetector,
        trace_data: dict[str, Any],
    ):
        self.receipt = receipt
        self.all_accounts = all_accounts
        self.settings = settings
        self.db = db
        self.trace_data = trace_data

    @property
    def allowed_accounts(self) -> list[dict[str, Any]]:
        allowed_numbers = {str(no) for no in self.settings.bexio_allowed_soll_accounts}
        return [
            {"id": a["id"], "account_no": a["account_no"], "name": a["name"]}
            for a in self.all_accounts
            if str(a.get("account_no")) in allowed_numbers
        ]

    @property
    def haben_bank_id(self) -> int | None:
        return next(
            (
                a["id"]
                for a in self.all_accounts
                if str(a.get("account_no"))
                == str(self.settings.bexio_haben_account_bank)
            ),
            None,
        )

    @property
    def haben_cash_id(self) -> int | None:
        return next(
            (
                a["id"]
                for a in self.all_accounts
                if str(a.get("account_no"))
                == str(self.settings.bexio_haben_account_cash)
            ),
            None,
        )

    @property
    def default_account_id(self) -> int | None:
        acc_id = (
            self.db.get_merchant_account(self.receipt.merchant_name)
            if self.receipt.merchant_name
            else None
        )
        return acc_id if acc_id else self.settings.default_booking_account_id

    @property
    def vat_account_map(self) -> dict[float, dict[str, Any]]:
        vat_map: dict[float, dict[str, Any]] = {}
        assignments = self.trace_data.get("step3_assignments", [])

        if not self.receipt.vat_breakdown:
            return vat_map

        merchant_vat_accounts = {}
        if self.receipt.merchant_name:
            merchant_vat_accounts = self.db.get_merchant_vat_accounts(
                self.receipt.merchant_name
            )

        for entry in self.receipt.vat_breakdown:
            acc_id = None
            if self.receipt.merchant_name:
                acc_id = merchant_vat_accounts.get(entry.rate)

            match = None
            if not acc_id:
                # Fallback to Step 3 assignments from trace
                match = next(
                    (a for a in assignments if a.get("vat_rate") == entry.rate), None
                )
                if match:
                    try:
                        acc_id = int(match.get("account_id"))
                    except (ValueError, TypeError):
                        acc_id = None

            if not acc_id:
                acc_id = self.default_account_id

            vat_map[entry.rate] = {
                "account_id": acc_id,
                "reasoning": match.get("reasoning") if match else None,
                "confidence": match.get("confidence") if match else None,
            }
        return vat_map
