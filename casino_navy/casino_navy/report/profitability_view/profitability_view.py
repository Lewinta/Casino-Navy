# Profitability View (FY) - Revenue, Total Expenses, Net Total
# Shows monthly buckets; returns [] when filters are missing.

# Profitability View (FY) - now driven by Accountant Mapper
import calendar
import json
import re
from datetime import date
from dateutil.relativedelta import relativedelta

import frappe
from frappe.utils.nestedset import get_descendants_of
from casino_navy.casino_navy.doctype.accountant_mapper.accountant_mapper import (
    _load_sections_from_mapper,
    _resolve_sections_leafs,
)

REPORT_NAME = "Profitability View"


def execute(filters=None):
    filters = filters or {}
    company = filters.get("company")
    fiscal_year = filters.get("fiscal_year")

    # Show empty grid if required filters are missing
    if not company or not fiscal_year:
        return [], [], None, None

    currency = frappe.db.get_value("Company", company, "default_currency") or "USD"

    # Periods for the fiscal year
    fy_start, fy_end = _get_fiscal_year_dates(fiscal_year)
    periods = _build_month_periods(fy_start, fy_end)
    key_index = {p["key"]: idx for idx, p in enumerate(periods)}
    n = len(periods)

    # --- Load mapping from Accountant Mapper ---
    # resolved = OrderedDict like:
    #   {
    #     "Revenue": {
    #        "leafs": {"4000-..", ...},
    #        "signs": {"4000-..": 1, ...},
    #        "formulas": []   # or [{"formula": "A - B", "sign": 1}, ...]
    #     },
    #     "Total Expenses": {...},
    #     "Net Total": {"leafs": set(), "formulas": [{"formula": "Revenue + Total Expenses"}]}
    #   }
    sections = _load_sections_from_mapper(REPORT_NAME, company)
    resolved = _resolve_sections_leafs(company, sections)
    section_labels = list(resolved.keys())

    # Universe of accounts
    all_leafs = sorted({leaf for info in resolved.values() for leaf in info["leafs"]})
    if not all_leafs:
        return _build_columns(periods), [], None, None

    # Pull monthly debit/credit for all leaf accounts in one go
    month_sums = _get_monthly_debit_credit(company, fy_start, fy_end, all_leafs)
    # month_sums = {account: {'YYYY-MM': {'debit': x, 'credit': y}}, ...}

    # Base series per section (from buckets)
    section_series = {label: [0.0] * n for label in section_labels}
    for label in section_labels:
        info = resolved[label]
        for acc in sorted(info["leafs"]):
            sign = info["signs"].get(acc, 1)  # use -1 in mapper for expense-style buckets
            for k, sums in (month_sums.get(acc) or {}).items():
                if k not in key_index:
                    continue
                i = key_index[k]
                debit = float(sums.get("debit") or 0.0)
                credit = float(sums.get("credit") or 0.0)
                net = credit - debit  # income-style net; flip with sign if needed
                section_series[label][i] += sign * net

    # Apply formula sections (if any). If a section has formulas, the formula result
    # REPLACES the bucket totals for that section (to avoid double counting).
    for label in section_labels:
        info = resolved[label]
        formulas = info.get("formulas") or []
        if not formulas:
            continue
        # Evaluate per period using current section_series as inputs
        out = [0.0] * n
        for i in range(n):
            # Build a dict with current period values of each section
            period_ctx = {k: section_series[k][i] for k in section_series}
            out[i] = _evaluate_formulas(period_ctx, formulas)
        section_series[label] = out

    # Build rows
    data = []
    for label in section_labels:
        row = _blank_row(label, periods, currency)
        for i, p in enumerate(periods):
            row[p["key"]] = section_series[label][i]
        row["total"] = sum(row[p["key"]] for p in periods)
        data.append(row)

    columns = _build_columns(periods)

    # Chart uses the same order as mapper sections
    chart = _build_chart(
        rows=data,
        periods=periods,
        currency=currency,
        colors=["#2563eb", "#ef4444", "#16a34a"]  # optional
    )

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
        periods.append({
            "key": key, "label": label,
            "from": cur, "to": date(cur.year, cur.month, last_day)
        })
        cur = (cur + relativedelta(months=1)).replace(day=1)
    return periods


def _build_columns(periods):
    cols = [{
        "label": "Bucket",
        "fieldname": "account",
        "fieldtype": "Data",
        "width": 260,
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


def _blank_row(name, periods, currency):
    row = {"account": name, "currency": currency, "total": 0.0}
    for p in periods:
        row[p["key"]] = 0.0
    return row


def _get_monthly_debit_credit(company, from_date, to_date, accounts):
    """
    Returns: {account: {'YYYY-MM': {'debit': sum_debit, 'credit': sum_credit}}}
    We keep both sides so we can apply signs at the section/account level.
    """
    if not accounts:
        return {}
    placeholders = ", ".join(["%s"] * len(accounts))
    sql = f"""
        SELECT
            gle.account,
            DATE_FORMAT(gle.posting_date, '%%Y-%%m-01') AS period_start,
            SUM(gle.debit)  AS s_debit,
            SUM(gle.credit) AS s_credit
        FROM `tabGL Entry` gle
        WHERE
            gle.company = %s
            AND gle.is_cancelled = 0
            AND gle.posting_date BETWEEN %s AND %s
            AND gle.account IN ({placeholders})
        GROUP BY gle.account, period_start
    """
    params = [company, from_date, to_date] + list(accounts)
    rows = frappe.db.sql(sql, params, as_dict=True)

    out = {}
    for r in rows:
        acc = r["account"]
        key = r["period_start"][:7]  # YYYY-MM
        out.setdefault(acc, {})[key] = {
            "debit": float(r["s_debit"] or 0),
            "credit": float(r["s_credit"] or 0),
        }
    return out


def _evaluate_formulas(section_totals_for_period, formulas):
    """
    Evaluate a list of formulas (each is {"formula": "...", "sign": +/-1}) against a dict like:
      {"Revenue": 1000.0, "Total Expenses": -800.0, ...}   # values for ONE period
    Returns a single float (sum of all formula results).
    """
    import re

    total = 0.0
    for f in formulas or []:
        expr = (f.get("formula") or "").strip()
        if not expr:
            continue

        # Replace section labels with their numeric values (whole-word, safe)
        safe = expr
        for lbl, val in section_totals_for_period.items():
            # NOTE: Correct word-boundary usage (\b), not \\b
            safe = re.sub(rf"\b{re.escape(lbl)}\b", str(val), safe)

        # Guardrail: only digits, operators, decimal points, parentheses, and spaces
        if re.search(r"[^0-9\.\+\-\*\/\(\) ]", safe):
            continue

        try:
            val = eval(safe) if safe.strip() else 0.0  # arithmetic only after sanitization
        except Exception:
            val = 0.0

        total += float(val) * float(f.get("sign", 1))

    return total

def _build_chart(rows, periods, currency="USD", colors=None):
    if not rows:
        return None
    labels = [p["label"] for p in periods]
    datasets = []
    for r in rows:
        datasets.append({
            "name": r["account"],
            "values": [r.get(p["key"], 0) for p in periods],
        })

    chart = {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "colors": (colors or [])[:len(datasets)],
        "barOptions": {"stacked": 0},
        "fieldtype": "Currency",
        "options": currency,
        "custom_options": json.dumps({
            "tooltip": {"fieldtype": "Currency", "options": currency},
            "axisOptions": {"shortenYAxisNumbers": 1}
        }),
    }
    return chart