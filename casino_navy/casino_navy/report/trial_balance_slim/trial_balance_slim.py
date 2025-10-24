# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

# We reuse the official Trial Balance logic so totals match exactly,
# and then slim the output down to only child accounts and closing columns.
from erpnext.accounts.report.trial_balance.trial_balance import (
    validate_filters as _validate_filters,
    get_data as _get_trial_balance_rows,
)

def execute(filters=None):
    """
    Trial Balance Slim
    - Shows only 3 columns: Account, Closing (Dr), Closing (Cr)
    - Excludes group accounts (shows child accounts only)
    """
    filters = frappe._dict(filters or {})
    _validate_filters(filters)

    # Get the full dataset from the standard Trial Balance
    full_rows = _get_trial_balance_rows(filters) or []
    
    # 1) Remove trailing empties
    while full_rows and (not full_rows[-1] or not full_rows[-1].get("account")):
        full_rows.pop()

    # 2) Remove trailing “Total” data row (even if it comes quoted)
    if full_rows and _is_total_row(full_rows[-1]):
        full_rows.pop()

    # Build a set of accounts that appear as parents, so we can exclude them
    parent_set = {r.get("parent_account") for r in full_rows if r.get("parent_account")}
    parent_set.discard(None)

    slim_rows = []
    for r in full_rows:
        account = r.get("account")

        # Skip separators / total rows / empty rows
        if not account:
            continue
        if account == _("Total"):
            continue

        # Exclude group accounts: any account that appears as a parent of others
        if account in parent_set:
            continue

        slim_rows.append({
            "account": account,
            # Keep currency in the row so Currency columns can reference it (even if hidden)
            "currency": r.get("currency"),
            "closing_debit": flt(r.get("closing_debit", 0.0), 3),
            "closing_credit": flt(r.get("closing_credit", 0.0), 3),
        })

    columns = get_columns()

    return columns, slim_rows


def get_columns():
    # Only 3 visible columns; include hidden currency field for proper currency rendering.
    return [
        {
            "fieldname": "account",
            "label": _("Account"),
            "fieldtype": "Link",
            "options": "Account",
            "width": 300,
        },
        {
            "fieldname": "currency",
            "label": _("Currency"),
            "fieldtype": "Link",
            "options": "Currency",
            "hidden": 1,  # keep hidden; used by Currency columns below
        },
        {
            "fieldname": "closing_debit",
            "label": _("Closing (Dr)"),
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
        {
            "fieldname": "closing_credit",
            "label": _("Closing (Cr)"),
            "fieldtype": "Currency",
            "options": "currency",
            "width": 130,
        },
    ]

def _is_total_row(r):
    # consider both account and account_name just in case
    label = (r.get("account") or r.get("account_name") or "").strip()
    # strip surrounding single/double quotes from weird returns like "'Total'"
    label = label.strip("'\"")
    return label in {"Total", _("Total")}