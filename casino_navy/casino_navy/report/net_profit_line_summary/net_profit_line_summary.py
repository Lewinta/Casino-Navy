# Net Profit Line Summary
# Copyright (c) 2025
# For license information, please see license.txt

import calendar
import json
import re
from datetime import date
from dateutil.relativedelta import relativedelta

import frappe
from frappe import _
from casino_navy.casino_navy.doctype.accountant_mapper.accountant_mapper import (
    _load_sections_from_mapper,
    _resolve_sections_leafs,
)

REPORT_NAME = "Net Profit Line Summary"


def execute(filters=None):
    filters = filters or {}
    company = filters.get("company")
    fiscal_year = filters.get("fiscal_year")
    _validate_required(company, fiscal_year)

    company_currency = _get_company_currency(company)
    fy_start, fy_end = _get_fiscal_year_dates(fiscal_year)
    start_limit = date(2025, 6, 1)
    if fy_start < start_limit:
        fy_start = start_limit

    periods = _build_month_periods(fy_start, fy_end)
    p_index = {p["key"]: idx for idx, p in enumerate(periods)}
    n = len(periods)

    sections = _load_sections_from_mapper(REPORT_NAME, company)
    resolved = _resolve_sections_leafs(company, sections)
    section_labels = list(resolved.keys())

    if not any(lbl.lower().startswith("rev") for lbl in section_labels):
        frappe.throw(_("Accountant Mapper for this report must have a 'Revenue' section."))
    if not any("cost of sales" in lbl.lower() or "cogs" in lbl.lower() for lbl in section_labels):
        frappe.throw(_("Accountant Mapper for this report must have a 'Cost of Sales' section."))

    all_accounts = sorted({leaf for info in resolved.values() for leaf in info["leafs"]})
    month_dc = _get_monthly_debit_credit(company, fy_start, fy_end, all_accounts)

    section_series = {lbl: [0.0] * n for lbl in section_labels}
    for label, info in resolved.items():
        for acc in sorted(info["leafs"]):
            sign = info["signs"].get(acc, 1)
            for key, sums in (month_dc.get(acc) or {}).items():
                i = p_index.get(key)
                if i is None:
                    continue
                debit = float(sums.get("debit") or 0.0)
                credit = float(sums.get("credit") or 0.0)
                net = credit - debit
                section_series[label][i] += sign * net

    for label, info in resolved.items():
        formulas = info.get("formulas") or []
        if not formulas:
            continue
        out = [0.0] * n
        for i in range(n):
            ctx = {k: section_series[k][i] for k in section_series}
            out[i] = _evaluate_formulas(ctx, formulas)
        section_series[label] = out

    rows = [_make_row(label, company_currency, periods, section_series[label]) for label in section_labels]
    columns = _build_columns(periods)
    chart = _build_chart(periods, company_currency, section_series, section_labels)

    accounts_by_section = {
        label: sorted(info.get("leafs") or [])
        for label, info in resolved.items()
        if info.get("leafs")
    }

    message = {"accounts_by_section": accounts_by_section}
    return columns, rows, message, chart


# --------------------------
# Helpers
# --------------------------

def _validate_required(company, fiscal_year):
    missing = [n for n, v in [("company", company), ("fiscal_year", fiscal_year)] if not v]
    if missing:
        frappe.throw(_("Missing filters: {0}").format(", ".join(missing)))


def _get_company_currency(company: str) -> str:
    return frappe.db.get_value("Company", company, "default_currency") or "USD"


def _get_fiscal_year_dates(fiscal_year_name: str):
    doc = frappe.db.get_value(
        "Fiscal Year",
        fiscal_year_name,
        ["year_start_date", "year_end_date"],
        as_dict=True,
    )
    if not doc:
        frappe.throw(_("Fiscal Year {0} not found").format(fiscal_year_name))
    return doc.year_start_date, doc.year_end_date


def _build_month_periods(start_date: date, end_date: date):
    periods = []
    cur = date(start_date.year, start_date.month, 1)
    last = date(end_date.year, end_date.month, 1)
    while cur <= last:
        last_day = calendar.monthrange(cur.year, cur.month)[1]
        from_dt = cur
        to_dt = date(cur.year, cur.month, last_day)
        label = f"{cur.strftime('%b')} {str(cur.year)[-2:]}"
        key = cur.strftime("%Y-%m")
        periods.append({"key": key, "label": label, "from": from_dt, "to": to_dt})
        cur = (cur + relativedelta(months=1)).replace(day=1)
    return periods


def _build_columns(periods):
    cols = [{"label": _("Account"), "fieldname": "account", "fieldtype": "Data", "width": 260}]
    for p in periods:
        cols.append({
            "label": _(p["label"]),
            "fieldname": p["key"],
            "fieldtype": "Currency",
            "options": "currency",
            "width": 110,
        })
    cols.append({
        "label": _("Total"),
        "fieldname": "total",
        "fieldtype": "Currency",
        "options": "currency",
        "width": 130,
    })
    return cols


def _get_monthly_debit_credit(company: str, from_date: date, to_date: date, accounts: list[str]):
    if not accounts:
        return {}

    placeholders = ", ".join(["%s"] * len(accounts))
    sql = f"""
        SELECT
            gle.account,
            DATE_FORMAT(gle.posting_date, '%%Y-%%m-01') AS period_start,
            SUM(gle.debit)  AS debit,
            SUM(gle.credit) AS credit
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

    out = {}
    for r in rows:
        acc = r["account"]
        key = r["period_start"][:7]
        out.setdefault(acc, {})[key] = {
            "debit": float(r.get("debit") or 0),
            "credit": float(r.get("credit") or 0),
        }
    return out


def _make_row(label: str, currency: str, periods, values: list[float]):
    row = {"account": label, "currency": currency}
    total = 0.0
    for i, p in enumerate(periods):
        val = float(values[i] if i < len(values) else 0)
        row[p["key"]] = val
        total += val
    row["total"] = total
    return row


def _evaluate_formulas(section_totals_for_period, formulas):
    total = 0.0
    for f in formulas or []:
        expr = (f.get("formula") or "").strip()
        if not expr:
            continue
        safe = expr
        for lbl, val in section_totals_for_period.items():
            safe = re.sub(rf"\b{re.escape(lbl)}\b", str(val), safe)
        if re.search(r"[^0-9\.\+\-\*\/\(\) ]", safe):
            continue
        try:
            val = eval(safe) if safe.strip() else 0.0
        except Exception:
            val = 0.0
        total += float(val) * float(f.get("sign", 1))
    return total


def _build_chart(periods, currency: str, section_series: dict, section_labels: list[str]):
    labels = [p["label"] for p in periods]
    datasets = [{"name": lbl, "values": section_series.get(lbl, [])} for lbl in section_labels]
    return {
        "type": "line",
        "data": {"labels": labels, "datasets": datasets},
        "custom_options": json.dumps({
            "tooltip": {"fieldtype": "Currency", "options": currency, "always_show_decimals": False},
            "axisOptions": {"shortenYAxisNumbers": 1}
        }),
        "fieldtype": "Currency",
        "options": currency,
    }
