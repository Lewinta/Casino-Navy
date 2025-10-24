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

    # Build data rows (one per section label from the mapper)
    data = []
    for label in section_labels:
        info = resolved[label]
        month_vals = [0.0] * n

        for acc in sorted(info["leafs"]):
            sign = info["signs"].get(acc, 1)  # default +1; set -1 in mapper only if you need to invert
            for k, amt in (amounts_by_account.get(acc) or {}).items():
                i = period_index_by_key.get(k)
                if i is None:
                    continue
                month_vals[i] += sign * amt

        row = {"account": label, "currency": currency}
        for i, p in enumerate(periods):
            row[p["key"]] = month_vals[i]
        row["total"] = sum(month_vals)
        data.append(row)

    columns = _build_columns(periods)
    chart = _build_chart(data, periods, currency)
    return columns, data, None, chart


# -------------------------- helpers --------------------------

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
        "fieldtype": "Data",
        "width": 300,
    }]
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