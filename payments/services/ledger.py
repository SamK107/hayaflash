from __future__ import annotations

from decimal import Decimal

from payments.models import (
    LedgerAccount,
    LedgerEntry,
    LedgerEntryType,
    PaymentTransaction,
)


def append_balanced_entries_for_success(pt: PaymentTransaction) -> None:
    """
    Double-entry for one successful payment: one debit + one credit of equal amounts.

    Caller must hold ``PaymentTransaction`` row locked (``select_for_update``).
    Idempotent: no-op if entries already exist.
    """
    if pt.ledger_entries.exists():
        return
    LedgerEntry.objects.bulk_create(
        [
            LedgerEntry(
                transaction=pt,
                entry_type=LedgerEntryType.DEBIT,
                amount=pt.amount,
                account=LedgerAccount.USER_WALLET,
            ),
            LedgerEntry(
                transaction=pt,
                entry_type=LedgerEntryType.CREDIT,
                amount=pt.amount,
                account=LedgerAccount.PLATFORM_COMMISSION,
            ),
        ]
    )


def ledger_balanced_for_payment(pt: PaymentTransaction) -> bool:
    qs = pt.ledger_entries.all()
    if qs.count() != 2:
        return False
    debit = Decimal("0")
    credit = Decimal("0")
    for row in qs:
        if row.entry_type == LedgerEntryType.DEBIT:
            debit += row.amount
        elif row.entry_type == LedgerEntryType.CREDIT:
            credit += row.amount
    return debit == credit == pt.amount
