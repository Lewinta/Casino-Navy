# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import calendar
import json
from datetime import date
from dateutil.relativedelta import relativedelta

import frappe
from frappe.utils.nestedset import get_descendants_of
from casino_navy.casino_navy.doctype.accountant_mapper.accountant_mapper import (
    _load_sections_from_mapper,
    _resolve_sections_leafs,
)

REPORT_NAME = "Expenses & Overhead"


def execute(filters=None):
    filters = filters or {}
    company = filters.get("company")
    fiscal_year = filters.get("fiscal_year")

    # If required filters are missing, return an empty table so the user can select them
    if not company or not fiscal_year:
        return [], [], None, None

    currency = frappe.db.get_value("Company", company, "default_currency") or "USD"

    # Fiscal year range & monthly periods
    fy_start, fy_end = _get_fiscal_year_dates(fiscal_year)
    periods = _build_month_periods(fy_start, fy_end)
    period_index_by_key = {p["key"]: idx for idx, p in enumerate(periods)}
    n = len(periods)

    # ---- Load mapping from Accountant Mapper ----
    # resolved (OrderedDict):
    #   {
    #     "Personnel Costs": {"leafs": {...}, "signs": {acc: 1, ...}, "formulas": []},
    #     "Licenses & Fees": {...},
    #     ...
    #   }
    sections = _load_sections_from_mapper(REPORT_NAME, company)
    resolved = _resolve_sections_leafs(company, sections)
    section_labels = list(resolved.keys())

    # Universe of accounts to query
    all_leafs = sorted({leaf for info in resolved.values() for leaf in info["leafs"]})
    if not all_leafs:
        # No accounts configured yet: return empty grid (columns only)
        return _build_columns(periods), [], None, None

    # Fetch monthly values for all accounts in one query
    # We keep the same sign convention you had before: expenses as (debit - credit)
    # amounts_by_account = {acc: {'YYYY-MM': amount}, ...}
    amounts_by_account = _get_monthly_amounts(company, fy_start, fy_end, all_leafs)

    # Build data rows (one per section label from the mapper) — CLICKABLE buckets
    data = []
    for label in section_labels:
        info = resolved[label]
        month_vals = [0.0] * n

        for acc in sorted(info["leafs"]):
            sign = info["signs"].get(acc, 1)
            for k, amt in (amounts_by_account.get(acc) or {}).items():
                i = period_index_by_key.get(k)
                if i is None:
                    continue
                month_vals[i] += sign * amt

        # Try to find a real group account to link this bucket to
        group_account = _resolve_group_account_for_section(company, label, sorted(info["leafs"]))
        meta = _get_account_meta(group_account) if group_account else {"account_name": "", "parent_account": "", "account_type": ""}

        data.append(_make_row_payload(
            account=group_account or "",     # clickable if resolved, else plain text
            display_label=label,             # keep showing the mapper label
            periods=periods,
            values=month_vals,
            currency=currency,
            year_start=fy_start,
            year_end=fy_end,
            parent_account=meta.get("parent_account", ""),
            account_type=meta.get("account_type", ""),
            bold=1
        ))

    columns = _build_columns(periods)
    chart = _build_chart(data, periods, currency)
    return columns, data, None, chart


# -------------------------- helpers --------------------------

from functools import lru_cache
from frappe import _  # already imported above

@lru_cache(maxsize=None)
def _get_account_meta(account_name: str):
    if not account_name:
        return {"account_name": "", "parent_account": "", "account_type": ""}
    row = frappe.db.get_value(
        "Account", account_name, ["account_name", "parent_account", "account_type"], as_dict=True
    ) or {}
    return {
        "account_name": (row.get("account_name") or "").strip() or account_name,
        "parent_account": row.get("parent_account") or "",
        "account_type": row.get("account_type") or "",
    }

@lru_cache(maxsize=None)
def _get_account_node(account_name: str):
    if not account_name:
        return {"parent_account": None, "is_group": 0, "company": None}
    row = frappe.db.get_value(
        "Account", account_name, ["parent_account", "is_group", "company"], as_dict=True
    ) or {}
    row.setdefault("parent_account", None)
    row["is_group"] = 1 if row.get("is_group") else 0
    return row

def _ancestor_chain(account_name: str):
    chain = []
    cur = account_name
    seen = {cur}
    while cur:
        node = _get_account_node(cur)
        parent = node.get("parent_account")
        if not parent or parent in seen:
            break
        chain.append(parent)   # nearest first
        seen.add(parent)
        cur = parent
    return chain

def _resolve_group_account_for_section(company: str, section_label: str, leafs: list[str]) -> str | None:
    # 1) If mapper label is an existing Account in this company → use it
    if frappe.db.exists("Account", {"name": section_label, "company": company}):
        return section_label
    if not leafs:
        return None
    # 2) deepest common ancestor of all leafs
    ref_chain = _ancestor_chain(leafs[0])
    common = set(ref_chain)
    for acc in leafs[1:]:
        common &= set(_ancestor_chain(acc))
        if not common:
            return None
    for candidate in ref_chain:  # nearest first
        if candidate in common:
            node = _get_account_node(candidate)
            if node.get("company") == company and node.get("is_group") == 1:
                return candidate
    return None

def _make_row_payload(
    account: str,              # real Account name or "" if non-clickable
    display_label: str,        # text shown in Account column
    periods, values: list[float],
    currency: str,
    year_start, year_end,
    parent_account: str = "",
    account_type: str = "",
    bold: int = 0,
):
    row = {
        "account": account,                     # clickable if non-empty
        "account_name": display_label,
        "parent_account": parent_account,
        "account_type": account_type,
        "year_start_date": year_start,
        "year_end_date": year_end,
        "from_date": year_start,
        "to_date": year_end,
        "currency": currency,
    }
    total = 0.0
    for i, p in enumerate(periods):
        v = float(values[i] if i < len(values) else 0)
        row[p["key"]] = v
        total += v
    row["total"] = total
    if bold:
        row["bold"] = 1
    return row

def _get_fiscal_year_dates(fy_name: str):
    doc = frappe.db.get_value(
        "Fiscal Year", fy_name, ["year_start_date", "year_end_date"], as_dict=True
    )
    if not doc:
        frappe.throw(f"Fiscal Year {fy_name} not found")
    return doc.year_start_date, doc.year_end_date


def _build_month_periods(start_date: date, end_date: date):
    periods = []
    cur = date(start_date.year, start_date.month, 1)
    last = date(end_date.year, end_date.month, 1)
    while cur <= last:
        last_day = calendar.monthrange(cur.year, cur.month)[1]
        key = cur.strftime("%Y-%m")
        label = f"{cur.strftime('%b')} {str(cur.year)[-2:]}"
        periods.append(
            {"key": key, "label": label, "from": cur, "to": date(cur.year, cur.month, last_day)}
        )
        cur = (cur + relativedelta(months=1)).replace(day=1)
    return periods


def _build_columns(periods):
    cols = [{
        "label": "Account / Bucket",
        "fieldname": "account",
        "fieldtype": "Link",
        "options": "Account",
        "width": 300,
        "align": "left",
    },
    {"label": "Account Name", "fieldname": "account_name", "fieldtype": "Data", "hidden": 1},
    {"label": "Parent Account", "fieldname": "parent_account", "fieldtype": "Data", "hidden": 1},
    {"label": "Account Type", "fieldname": "account_type", "fieldtype": "Data", "hidden": 1},
    {"label": "Year Start", "fieldname": "year_start_date", "fieldtype": "Date", "hidden": 1},
    {"label": "Year End", "fieldname": "year_end_date", "fieldtype": "Date", "hidden": 1},
    {"label": "From Date", "fieldname": "from_date", "fieldtype": "Date", "hidden": 1},
    {"label": "To Date", "fieldname": "to_date", "fieldtype": "Date", "hidden": 1},
    ]
    for p in periods:
        cols.append({
            "label": p["label"],
            "fieldname": p["key"],
            "fieldtype": "Currency",
            "options": "currency",
            "width": 110,
        })
    cols.append({
        "label": "Total",
        "fieldname": "total",
        "fieldtype": "Currency",
        "options": "currency",
        "width": 130,
    })
    return cols

def _get_monthly_amounts(company, from_date, to_date, accounts):
    if not accounts:
        return {}
    placeholders = ", ".join(["%s"] * len(accounts))
    sql = f"""
        SELECT
            gle.account,
            DATE_FORMAT(gle.posting_date, '%%Y-%%m-01') AS period_start,
            SUM(gle.debit - gle.credit) AS amount
        FROM `tabGL Entry` gle
        WHERE
            gle.company = %s
            AND gle.is_cancelled = 0
            AND gle.posting_date BETWEEN %s AND %s
            AND gle.account IN ({placeholders})
            AND gle.posting_date >= '2025-06-01'
        GROUP BY gle.account, period_start
    """
    params = [company, from_date, to_date] + accounts
    rows = frappe.db.sql(sql, params, as_dict=True)

    result = {}
    for r in rows:
        acc = r["account"]
        key = r["period_start"][:7]  # 'YYYY-MM'
        result.setdefault(acc, {})[key] = float(r["amount"] or 0)
    return result


def _build_chart(rows, periods, currency="USD"):
    if not rows:
        return None
    labels = [p["label"] for p in periods]
    colors = ["#2563eb", "#16a34a", "#f59e0b", "#ef4444", "#8b5cf6", "#10b981"]  # up to 6 buckets

    datasets = []
    for r in rows:
        values = [r.get(p["key"], 0) for p in periods]
        datasets.append({"name": r["account"], "values": values})

    return {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "colors": colors[:len(datasets)],
        "barOptions": {"stacked": 0},
        "fieldtype": "Currency",
        "options": currency,
        "custom_options": json.dumps({
            "tooltip": {"fieldtype": "Currency", "options": currency},
            "axisOptions": {"shortenYAxisNumbers": 1},
        }),
    }