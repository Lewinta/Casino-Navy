# Net Profit Line Summary
# Copyright (c) 2025
# For license information, please see license.txt

import json
import frappe
import calendar
from frappe import _
from datetime import date
from dateutil.relativedelta import relativedelta
from frappe.utils.nestedset import get_descendants_of


# ---- Configure the key accounts here (exact account names) ----
# Revenue is a GROUP account; we will roll up all its leaf children
REVENUE_GROUP = "40000 - INCOME / REVENUE - X2"

# Cost of Sales = children of this group + the extra accounts below
COST_GROUP = "50000 - GAME PROVIDERS - X2"
COST_EXTRA_ACCOUNTS = [
    "68000 - Commission fee Deposits - X2",
    "68006 - Commission Fee Deposits EUR - X2",  # in EUR; we rely on base values from GL
]


def execute(filters=None):
    if not filters:
        filters = {}

    company = filters.get("company")
    fiscal_year = filters.get("fiscal_year")

    _validate_required(company, fiscal_year)

    # Company currency (for display/format only)
    company_currency = _get_company_currency(company)

    # Build monthly periods for the fiscal year
    fy_start, fy_end = _get_fiscal_year_dates(fiscal_year)
    periods = _build_month_periods(fy_start, fy_end)  # [{key,label,from,to}]
    p_index = {p["key"]: idx for idx, p in enumerate(periods)}

    # Resolve target account lists
    revenue_accounts = _resolve_group_leaf_accounts(company, REVENUE_GROUP)
    cost_accounts = _resolve_cost_accounts(company)

    # One query for all needed accounts
    all_accounts = sorted(set(revenue_accounts + cost_accounts))
    gl = _get_monthly_debit_credit(company, fy_start, fy_end, all_accounts)
    # gl: {account: {'YYYY-MM': {'debit': x, 'credit': y}, ...}, ...}

    # Prepare monthly arrays
    rev_month = [0.0] * len(periods)
    cost_month = [0.0] * len(periods)

    # --- Revenue (group roll-up): + (credit - debit) across ALL revenue leaf accounts ---
    for acc in revenue_accounts:
        acc_map = gl.get(acc, {}) or {}
        for key, sums in acc_map.items():
            if key in p_index:
                rev_month[p_index[key]] += float(sums.get("credit", 0) - sums.get("debit", 0))

    # --- Cost of Sales: + (debit - credit) across ALL cost accounts (group children + extras) ---
    for acc in cost_accounts:
        acc_map = gl.get(acc, {}) or {}
        for key, sums in acc_map.items():
            if key in p_index:
                cost_month[p_index[key]] += float(sums.get("debit", 0) - sums.get("credit", 0))

    # Net Profit = Revenue - Cost
    net_month = [rev_month[i] - cost_month[i] for i in range(len(periods))]

    # Rows (Revenue, Cost of Sales, Net Profit)
    rows = []

    # Revenue → clickable to REVENUE_GROUP
    rev_meta = _get_account_meta(REVENUE_GROUP)
    rows.append(_make_row_payload(
        account=REVENUE_GROUP,
        display_label=_("Revenue"),
        periods=periods,
        values=rev_month,
        currency=company_currency,
        year_start=fy_start,
        year_end=fy_end,
        parent_account=rev_meta["parent_account"],
        account_type=rev_meta["account_type"],
        bold=1,
    ))

    # Cost of Sales → clickable to COST_GROUP
    cost_meta = _get_account_meta(COST_GROUP)
    rows.append(_make_row_payload(
        account=COST_GROUP,
        display_label=_("Cost of Sales"),
        periods=periods,
        values=cost_month,
        currency=company_currency,
        year_start=fy_start,
        year_end=fy_end,
        parent_account=cost_meta["parent_account"],
        account_type=cost_meta["account_type"],
        bold=1,
    ))

    # Net Profit → derived, non-clickable
    rows.append(_make_row_payload(
        account="",
        display_label=_("Net Profit"),
        periods=periods,
        values=net_month,
        currency=company_currency,
        year_start=fy_start,
        year_end=fy_end,
        bold=1,
    ))

    # Columns
    columns = _build_columns(periods)

    # Chart
    chart = _build_chart(periods, company_currency, rev_month, cost_month, net_month)

    return columns, rows, None, chart


# --------------------------
# Helpers
# --------------------------

from functools import lru_cache

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

def _make_row_payload(
    account: str,              # real Account name or "" for non-clickable
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
    """Return a list of monthly periods covering the fiscal year:
       [{key:'2025-01', label:'Jan 25', from: date, to: date}, ...]"""
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
    cols = [
        {
            "label": _("Account"),
            "fieldname": "account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 260,
            "align": "left",
        },
        {"label": _("Account Name"), "fieldname": "account_name", "fieldtype": "Data", "hidden": 1},
        {"label": _("Parent Account"), "fieldname": "parent_account", "fieldtype": "Data", "hidden": 1},
        {"label": _("Account Type"), "fieldname": "account_type", "fieldtype": "Data", "hidden": 1},
        {"label": _("Year Start"), "fieldname": "year_start_date", "fieldtype": "Date", "hidden": 1},
        {"label": _("Year End"), "fieldname": "year_end_date", "fieldtype": "Date", "hidden": 1},
        {"label": _("From Date"), "fieldname": "from_date", "fieldtype": "Date", "hidden": 1},
        {"label": _("To Date"), "fieldname": "to_date", "fieldtype": "Date", "hidden": 1},
    ]
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


def _resolve_group_leaf_accounts(company: str, parent_account: str) -> list[str]:
    """Return all leaf (is_group=0) accounts under a given parent in the same company.
       If the given account itself is a leaf, returns [parent_account]."""
    is_group = frappe.db.get_value("Account", parent_account, "is_group")
    if not is_group:
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


def _resolve_cost_accounts(company: str) -> list[str]:
    """Return all accounts contributing to Cost of Sales:
       - All leaf descendants of COST_GROUP (same company, is_group=0)
       - Plus the COST_EXTRA_ACCOUNTS (as-is)."""
    descendants = get_descendants_of("Account", COST_GROUP) or []
    leafs = []
    if descendants:
        leafs = frappe.get_all(
            "Account",
            filters={"name": ["in", descendants], "company": company, "is_group": 0},
            pluck="name",
        )
    # Merge + de-dup
    return sorted(set(leafs + COST_EXTRA_ACCOUNTS))


def _get_monthly_debit_credit(company: str, from_date: date, to_date: date, accounts: list[str]):
    """Return dict {account: {'YYYY-MM': {'debit': d, 'credit': c}, ...}, ...}
       Using base values from GL Entry (company currency)."""
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
            AND gle.posting_date >= '2025-06-01'
        GROUP BY gle.account, period_start
    """
    params = [company, from_date, to_date] + accounts
    rows = frappe.db.sql(sql, params, as_dict=True)

    out = {}
    for r in rows:
        acc = r["account"]
        key = r["period_start"][:7]  # YYYY-MM
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


def _build_chart(periods, currency: str, rev_month, cost_month, net_month):
    labels = [p["label"] for p in periods]
    chart = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                {"name": _("Revenue"), "values": rev_month},
                {"name": _("Cost of Sales"), "values": cost_month},
                {"name": _("Gross Profit"), "values": net_month},
            ],
        },
        "custom_options": json.dumps({
            "tooltip": {
                "fieldtype": "Currency",
                "options": currency,
                "always_show_decimals": False
            },
            "axisOptions": {
                "shortenYAxisNumbers": 1
            }
        }),
        "fieldtype": "Currency",
        "options": currency,
    }
    return chart