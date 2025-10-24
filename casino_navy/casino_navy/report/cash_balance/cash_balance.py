# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import calendar
import json
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.nestedset import get_descendants_of
from casino_navy.casino_navy.doctype.accountant_mapper.accountant_mapper import _load_sections_from_mapper, _resolve_sections_leafs

# ---- Configure the GROUP accounts here (exact account names) ----
REPORT_NAME = "Cash Balance"
CASH_GROUPS = {
    _("Bank Accounts"): "12000 - Bank Accounts - X2",
    _("E-Wallets"): "13000 - E-Wallets - X2",
    _("Crypto Wallets"): "14000 - Crypto Wallets - X2",
}


def execute(filters=None):
    
    filters = filters or {}
    company = filters.get("company")
    fiscal_year = filters.get("fiscal_year")
    summary = cint(filters.get("summary", 1))
    selected_account = (filters.get("account") or "").strip()

    _validate_required(company, fiscal_year)

    currency = _get_company_currency(company)
    fy_start, fy_end = _get_fiscal_year_dates(fiscal_year)
    periods = _build_month_periods(fy_start, fy_end)
    n = len(periods)

    # Load sections from Accountant Mapper
    sections = _load_sections_from_mapper(REPORT_NAME, company)
    resolved = _resolve_sections_leafs(company, sections)
    # resolved = OrderedDict like:
    #   {"Bank Accounts": {"leafs": set(...), "signs": {"acc": 1, ...}, "formulas": []}, ...}

    # Build a stable list of labels (mapper sort order already applied upstream)
    section_labels = list(resolved.keys())

    # Universe of allowed leaf accounts across all sections
    allowed_leafs = sorted({leaf for info in resolved.values() for leaf in info["leafs"]})
    if not allowed_leafs:
        return _build_columns(periods), [], None, _build_chart_if_summary(periods, currency, summary, {})

    # Opening and monthly movements
    day_before = fy_start - timedelta(days=1)
    opening = _get_opening_balances(company, day_before, allowed_leafs)
    monthly_mov = _get_monthly_movements(company, fy_start, fy_end, allowed_leafs)

    # Monthly balances per account (cumulative)
    account_balances = {}
    for acc in allowed_leafs:
        start_bal = float(opening.get(acc, 0.0))
        series = []
        running = start_bal
        for p in periods:
            mov = float((monthly_mov.get(acc, {}) or {}).get(p["key"], 0.0))
            running += mov
            series.append(running)
        account_balances[acc] = series

    # Aggregate per section (apply per-account sign if future mappers use it)
    group_series = {}
    for label in section_labels:
        info = resolved[label]
        sums = [0.0] * n
        for acc in sorted(info["leafs"]):
            acc_series = account_balances.get(acc, [0.0] * n)
            sign = info["signs"].get(acc, 1)
            for i in range(n):
                sums[i] += sign * acc_series[i]
        group_series[label] = sums

    columns = _build_columns(periods)
    rows = []

    if summary:
        # SUMMARY MODE: one row per section from the mapper
        for label in section_labels:
            rows.append(_make_row(label, currency, periods, group_series.get(label, [0.0]*n)))
        chart = _build_chart_if_summary(periods, currency, summary, group_series, section_labels)
        return columns, rows, None, chart

    # DETAILED MODE
    if selected_account:
        # Show descendants of the selected account, limited to allowed_leafs
        # (this preserves your previous drill-down behavior)
        target_leafs = _safe_intersection(
            _resolve_group_leaf_accounts(company, selected_account),
            allowed_leafs,
        )
        if not target_leafs and selected_account in allowed_leafs:
            target_leafs = [selected_account]

        if target_leafs:
            rows.append({"account": selected_account, "currency": currency, "bold": 1})
            subtotal = [0.0] * n
            for acc in sorted(target_leafs):
                series = account_balances.get(acc, [0.0] * n)
                rows.append(_make_row(acc, currency, periods, series))
                for i in range(n):
                    subtotal[i] += series[i]
            if _is_group_account(selected_account):
                rows.append(_make_row(_("{0} - Subtotal").format(selected_account), currency, periods, subtotal))
            return columns, rows, None, None
        # else fall through to full detailed view

    # Full detailed view grouped by mapper sections
    for label in section_labels:
        info = resolved[label]
        rows.append({"account": f"{label}", "currency": currency, "bold": 1})
        section_subtotal = [0.0] * n
        for acc in sorted(info["leafs"]):
            series = account_balances.get(acc, [0.0] * n)
            sign = info["signs"].get(acc, 1)
            signed = [sign * v for v in series]
            rows.append(_make_row(acc, currency, periods, signed))
            for i in range(n):
                section_subtotal[i] += signed[i]
        rows.append(_make_row(_("{0} - Subtotal").format(label), currency, periods, section_subtotal))

    return columns, rows, None, None


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
        label = f"{cur.strftime('%b')} {str(cur.year)[-2:]}"
        key = cur.strftime("%Y-%m")
        periods.append({"key": key, "label": label, "from": cur, "to": date(cur.year, cur.month, last_day)})
        cur = (cur + relativedelta(months=1)).replace(day=1)
    return periods


def _build_columns(periods):
    cols = [{"label": _("Account"), "fieldname": "account", "fieldtype": "Data", "width": 300}]
    for p in periods:
        cols.append({
            "label": _(p["label"]),
            "fieldname": p["key"],
            "fieldtype": "Currency",
            "options": "currency",
            "width": 110,
        })
    cols.append({"label": _("Total"), "fieldname": "total", "fieldtype": "Currency", "options": "currency", "width": 130})
    return cols


def _resolve_group_leaf_accounts(company: str, parent_account: str) -> list[str]:
    """Return all leaf accounts under a given parent (or the account itself if it is leaf)."""
    is_group = frappe.db.get_value("Account", parent_account, "is_group")
    if cint(is_group) == 0:
        return [parent_account]

    descendants = get_descendants_of("Account", parent_account) or []
    if not descendants:
        return []

    leafs = frappe.get_all(
        "Account",
        filters={"name": ["in", descendants], "company": company, "is_group": 0},
        pluck="name",
    )
    return sorted(leafs)


def _is_group_account(account_name: str) -> bool:
    val = frappe.db.get_value("Account", account_name, "is_group")
    try:
        return cint(val) == 1
    except Exception:
        return False


def _get_opening_balances(company: str, as_of_date: date, accounts: list[str]):
    if not accounts:
        return {}
    placeholders = ", ".join(["%s"] * len(accounts))
    sql = f"""
        SELECT gle.account, SUM(gle.debit - gle.credit) AS bal
        FROM `tabGL Entry` gle
        WHERE gle.company = %s
          AND gle.is_cancelled = 0
          AND gle.posting_date <= %s
          AND gle.account IN ({placeholders})
        GROUP BY gle.account
    """
    params = [company, as_of_date] + accounts
    rows = frappe.db.sql(sql, params, as_dict=True)
    return {r["account"]: float(r.get("bal") or 0.0) for r in rows}


def _get_monthly_movements(company: str, from_date: date, to_date: date, accounts: list[str]):
    if not accounts:
        return {}
    placeholders = ", ".join(["%s"] * len(accounts))
    sql = f"""
        SELECT
            gle.account,
            DATE_FORMAT(gle.posting_date, '%%Y-%%m-01') AS period_start,
            SUM(gle.debit - gle.credit) AS movement
        FROM `tabGL Entry` gle
        WHERE gle.company = %s
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
        out.setdefault(acc, {})[key] = float(r.get("movement") or 0.0)
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


def _sum_series(acc_list, account_balances, n):
    out = [0.0] * n
    for acc in acc_list or []:
        series = account_balances.get(acc, [0.0] * n)
        for i in range(n):
            out[i] += series[i]
    return out


def _safe_intersection(a_list, b_list):
    a = set(a_list or [])
    b = set(b_list or [])
    return sorted(a & b)


def _build_chart_if_summary(periods, currency: str, summary: int, group_series: dict, section_labels: list[str]):
    """Only build chart when summary is checked."""
    if not summary:
        return None
    labels = [p["label"] for p in periods]
    datasets = [{"name": label, "values": group_series.get(label, [])} for label in section_labels]
    return {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "custom_options": json.dumps({
            "tooltip": {"fieldtype": "Currency", "options": currency, "always_show_decimals": False},
            "axisOptions": {"shortenYAxisNumbers": 1},
        }),
        "fieldtype": "Currency",
        "options": currency,
    }