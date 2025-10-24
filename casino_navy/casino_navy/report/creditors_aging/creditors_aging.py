# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.report.accounts_receivable_summary.accounts_receivable_summary import (
    AccountsReceivableSummary,
)


def execute(filters=None):
    filters = filters or {}
    args = {
        "account_type": "Payable",
        "party_type": "Supplier",
        "naming_by": ["Buying Settings", "supp_master_name"],
    }

    # Forward full tuple (columns, data, message, chart, report_summary)
    result = AccountsReceivableSummary(filters).run(args)

    # Defensive unpack
    if not (isinstance(result, (list, tuple)) and len(result) >= 2):
        return result

    columns, data = result[0], result[1]
    message = result[2] if len(result) > 2 else None
    chart = result[3] if len(result) > 3 else None
    report_summary = result[4] if len(result) > 4 else None

    # Optional grouping by Supplier Type
    if frappe.utils.cint(filters.get("group_by_party_type")):
        data = _group_by_supplier_type(data)
        columns = _columns_grouped(columns, data)

    # If the AR summary logic didn’t build a chart for Payables, build one here.
    if not chart:
        chart = _build_aging_chart(data, filters)

    return columns, data, message, chart, report_summary


# -----------------------------
# Grouping helpers
# -----------------------------

def _group_by_supplier_type(rows: List[dict]) -> List[dict]:
    """Aggregate Accounts Receivable Summary rows by Supplier.supplier_type.

    Expects each row to contain the supplier key in either 'party' or 'supplier'.
    We sum all numeric fields (incl. aging buckets range1..range5) and keep the
    currency if all rows in a bucket share the same currency; otherwise leave blank.
    """
    if not rows:
        return []

    # 1) Find which field contains the supplier name in returned rows
    supplier_field = None
    for candidate in ("supplier", "party"):
        if candidate in rows[0]:
            supplier_field = candidate
            break
    if not supplier_field:
        # Nothing we can do—return untouched
        return rows

    suppliers = [r.get(supplier_field) for r in rows if r.get(supplier_field)]
    stype_map = _get_supplier_types_map(suppliers)  # name -> supplier_type

    # 2) Bucketize & aggregate
    buckets: Dict[str, dict] = {}

    # Identify numeric keys to sum (detect from the first row and keep flexible)
    numeric_keys = _detect_numeric_keys(rows)

    for r in rows:
        supplier = r.get(supplier_field)
        if not supplier:
            continue
        stype = stype_map.get(supplier) or _("(Unspecified)")

        if stype not in buckets:
            buckets[stype] = {"supplier_type": stype}

        acc = buckets[stype]

        # Sum numeric fields
        for k in numeric_keys:
            acc[k] = flt(acc.get(k)) + flt(r.get(k))

        # Try to keep a consistent currency per group; if mixed, blank it
        cur = r.get("currency")
        if "currency" not in acc:
            acc["currency"] = cur
        elif acc["currency"] != cur:
            acc["currency"] = None  # mixed currencies; leave blank

    # 3) Produce a stable sorted list (by Supplier Type asc)
    grouped = list(buckets.values())
    grouped.sort(key=lambda d: (d.get("supplier_type") or ""))

    return grouped


def _get_supplier_types_map(suppliers: Iterable[str]) -> Dict[str, str]:
    """Fetch supplier_type for the suppliers present in the result set in one shot."""
    unique = sorted({s for s in suppliers if s})
    if not unique:
        return {}

    rows = frappe.get_all(
        "Supplier",
        filters={"name": ["in", unique]},
        fields=["name", "supplier_type"],
        limit_page_length=0,
    )
    return {r["name"]: r.get("supplier_type") for r in rows}


def _detect_numeric_keys(rows: List[dict]) -> List[str]:
    """Heuristically detect numeric fields we should aggregate.

    We keep:
      - common AR Summary keys: outstanding, invoiced_amount, paid_amount, credit_note
      - aging buckets: range1..range5
      - totals like total_outstanding if present
    We exclude obvious non-numeric/id/name fields.
    """
    if not rows:
        return []

    preferred_numeric = {
        "outstanding",
        "invoiced_amount",
        "paid_amount",
        "credit_note",
        "total_outstanding",
        "range1",
        "range2",
        "range3",
        "range4",
        "range5",
    }

    sample = rows[0].keys()
    numeric = []
    for k in sample:
        if k in preferred_numeric or k.startswith("range"):
            # further guard: make sure at least one row has a number-ish value
            if any(isinstance(flt(r.get(k)), (int, float)) for r in rows):
                numeric.append(k)

    # Keep a consistent order: buckets then common amounts if present
    order_hint = ["range1", "range2", "range3", "range4", "range5",
                  "outstanding", "total_outstanding",
                  "invoiced_amount", "paid_amount", "credit_note"]
    numeric = sorted(set(numeric), key=lambda x: (order_hint.index(x) if x in order_hint else 999, x))
    return numeric


def _columns_grouped(base_columns: List[dict], grouped_rows: List[dict]) -> List[dict]:
    """Build a columns array appropriate for the grouped view.

    We’ll show:
      - Supplier Type (Data)
      - Currency (if it exists)
      - Detected numeric columns in a sensible order (aging buckets, totals)
    """
    # Figure out which numeric keys exist
    numeric_keys = _detect_numeric_keys(grouped_rows) if grouped_rows else []

    columns = [
        {"fieldname": "supplier_type", "label": _("Supplier Type"), "fieldtype": "Data", "width": 180},
    ]

    if grouped_rows and "currency" in grouped_rows[0]:
        columns.append({"fieldname": "currency", "label": _("Currency"), "fieldtype": "Data", "width": 90})

    # Add numeric columns
    labels_map = {
        "range1": _("0–30"),
        "range2": _("31–60"),
        "range3": _("61–90"),
        "range4": _("91–120"),
        "range5": _(">120"),
        "outstanding": _("Outstanding"),
        "total_outstanding": _("Total Outstanding"),
        "invoiced_amount": _("Invoiced"),
        "paid_amount": _("Paid"),
        "credit_note": _("Credit Note"),
    }
    for k in numeric_keys:
        columns.append({"fieldname": k, "label": labels_map.get(k, k.replace("_", " ").title()),
                        "fieldtype": "Currency", "width": 120})

    return columns


# -----------------------------
# Chart helper (unchanged)
# -----------------------------

def _build_aging_chart(data, filters):
    """Build an aging bar chart from the summary rows."""
    r1 = int(filters.get("range1", 30))
    r2 = int(filters.get("range2", 60))
    r3 = int(filters.get("range3", 90))
    r4 = int(filters.get("range4", 120))

    labels = [
        _(f"0–{r1}"),
        _(f"{r1+1}–{r2}"),
        _(f"{r2+1}–{r3}"),
        _(f"{r3+1}–{r4}"),
        _(f">{r4}"),
    ]

    bucket_keys = ["range1", "range2", "range3", "range4", "range5"]

    totals = []
    for key in bucket_keys:
        totals.append(sum(flt(row.get(key)) for row in data))

    chart = {
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "name": _("Outstanding Payables"),
                    "values": totals,
                }
            ],
        },
        "type": "percentage",
    }
    return chart