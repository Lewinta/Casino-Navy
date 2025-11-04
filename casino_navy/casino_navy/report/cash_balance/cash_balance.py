# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import calendar
import json
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

import frappe
from frappe import _
from frappe.utils import cint
from functools import lru_cache
from frappe.utils.nestedset import get_descendants_of
from casino_navy.casino_navy.doctype.accountant_mapper.accountant_mapper import (
    _load_sections_from_mapper,
    _resolve_sections_leafs,
)

# ---- Configure the GROUP accounts here (exact account names) ----
REPORT_NAME = "Cash Balance"


def execute(filters=None):
    filters = filters or {}
    company = filters.get("company")
    fiscal_year = filters.get("fiscal_year")
    selected_account = (filters.get("account") or "").strip()
    summary = cint(filters.get("summary"))

    _validate_required(company, fiscal_year)

    currency = _get_company_currency(company)
    fy_start, fy_end = _get_fiscal_year_dates(fiscal_year)
    periods = _build_month_periods(fy_start, fy_end)
    n = len(periods)

    # Load sections from Accountant Mapper
    sections = _load_sections_from_mapper(REPORT_NAME, company)
    resolved = _resolve_sections_leafs(company, sections)

    section_labels = list(resolved.keys())

    # Universe of allowed leaf accounts across all sections
    allowed_leafs = sorted({leaf for info in resolved.values() for leaf in info["leafs"]})
    if not allowed_leafs:
        return _build_columns(periods), [], None, None

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

    columns = _build_columns(periods)
    rows = []

    # Drill-down view for a selected account/group (kept as-is; no subtotals)
    if selected_account:
        target_leafs = _safe_intersection(
            _resolve_group_leaf_accounts(company, selected_account),
            allowed_leafs,
        )
        if not target_leafs and selected_account in allowed_leafs:
            target_leafs = [selected_account]

        if target_leafs:
            header_series = [0.0] * n
            for acc in sorted(target_leafs):
                series = account_balances.get(acc, [0.0] * n)
                for i in range(n):
                    header_series[i] += series[i]

            rows.append(_make_row_payload(
                account="",  # keep header non-clickable
                display_label=selected_account,
                periods=periods,
                values=header_series,
                currency=currency,
                year_start=fy_start,
                year_end=fy_end,
                bold=1
            ))

            for acc in sorted(target_leafs):
                series = account_balances.get(acc, [0.0] * n)
                rows.append(_make_row_payload(
                    account=acc,
                    display_label=_get_account_meta(acc)["account_name"] or acc,
                    periods=periods,
                    values=series,
                    currency=currency,
                    year_start=fy_start,
                    year_end=fy_end,
                    parent_account=_get_account_meta(acc)["parent_account"],
                    account_type=_get_account_meta(acc)["account_type"],
                    bold=0
                ))

            return columns, rows, None, None
        # else fall through

    # SUMMARY MODE → groups only + CHART (rows clickable to GL via group account)
    if summary:
        group_series = {}
        for label in section_labels:
            info = resolved[label]

            # find a real group account to link
            group_account = _resolve_group_account_for_section(
                company, label, sorted(info["leafs"])
            )
            meta = _get_account_meta(group_account) if group_account else {"account_name": None, "parent_account": None, "account_type": None}

            # roll-up series
            header_series = [0.0] * n
            for acc in sorted(info["leafs"]):
                sign = info["signs"].get(acc, 1)
                series = account_balances.get(acc, [0.0] * n)
                for i in range(n):
                    header_series[i] += sign * series[i]

            group_series[label] = header_series

            # IMPORTANT: set account=group_account to make it clickable;
            # keep display_label = mapper label so UI shows your section name
            rows.append(_make_row_payload(
                account=group_account or "",          # clickable if resolved
                display_label=label,                  # show your section label
                periods=periods,
                values=header_series,
                currency=currency,
                year_start=fy_start,
                year_end=fy_end,
                parent_account=meta.get("parent_account"),
                account_type=meta.get("account_type"),
                bold=1
            ))

        chart = _build_summary_chart(periods, currency, group_series, section_labels)
        return columns, rows, None, chart

    # DETAIL MODE → leaf accounts only, no chart
    for label in section_labels:
        info = resolved[label]
        for acc in sorted(info["leafs"]):
            meta = _get_account_meta(acc)
            sign = info["signs"].get(acc, 1)
            series = account_balances.get(acc, [0.0] * n)
            signed = [sign * v for v in series]

            rows.append(_make_row_payload(
                account=acc,                                # real account → clickable
                display_label=meta["account_name"] or acc,
                periods=periods,
                values=signed,
                currency=currency,
                year_start=fy_start,
                year_end=fy_end,
                parent_account=meta["parent_account"],
                account_type=meta["account_type"],
                bold=0
            ))
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
    cols = [
        # clickable like financial statements
        {"label": _("Account"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 300, "align": "left"},

        # hidden helpers used by formatter / routing
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
          AND gle.posting_date >= '2025-06-01'
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
          AND gle.posting_date >= '2025-06-01'
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


def _make_row_payload(
    account: str,                 # real Account name, or ""/None for group rows
    display_label: str,           # what to show in the Account column
    periods, values: list[float],
    currency: str,
    year_start, year_end,
    parent_account: str | None = None,
    account_type: str | None = None,
    bold: int = 0,
):
    row = {
        "account": account or "",                 # leave empty for non-real groups
        "account_name": display_label,
        "parent_account": parent_account or "",
        "account_type": account_type or "",
        "year_start_date": year_start,
        "year_end_date": year_end,
        "from_date": year_start,                  # let GL pick either pair
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


def _safe_intersection(a_list, b_list):
    a = set(a_list or [])
    b = set(b_list or [])
    return sorted(a & b)


@lru_cache(maxsize=None)
def _get_account_meta(account_name: str):
    if not account_name:
        return {"account_name": account_name, "parent_account": None, "account_type": None}
    row = frappe.db.get_value(
        "Account", account_name, ["account_name", "parent_account", "account_type"], as_dict=True
    ) or {}
    return {
        "account_name": row.get("account_name") or account_name,
        "parent_account": row.get("parent_account"),
        "account_type": row.get("account_type"),
    }

from functools import lru_cache

@lru_cache(maxsize=None)
def _get_account_node(account_name: str):
    """Cached minimal info for ancestor traversal."""
    if not account_name:
        return {"parent_account": None, "is_group": 0, "company": None}
    row = frappe.db.get_value(
        "Account",
        account_name,
        ["parent_account", "is_group", "company"],
        as_dict=True,
    ) or {}
    # normalize
    row.setdefault("parent_account", None)
    row["is_group"] = cint(row.get("is_group") or 0)
    return row

def _ancestor_chain(account_name: str):
    """Return list [parent, grandparent, ..., top] for an account."""
    chain = []
    cur = account_name
    seen = set([cur])
    while True:
        node = _get_account_node(cur)
        parent = node.get("parent_account")
        if not parent or parent in seen:
            break
        chain.append(parent)
        seen.add(parent)
        cur = parent
    return chain

def _resolve_group_account_for_section(company: str, section_label: str, leafs: list[str]) -> str | None:
    """
    Prefer: if section label is an existing Account in this company → use it.
    Else: pick the deepest common ancestor (group account) across all leafs.
    """
    # 1) Direct match on label
    if frappe.db.exists("Account", {"name": section_label, "company": company}):
        return section_label

    if not leafs:
        return None

    # 2) LCA over leafs (by ancestor set intersection, choosing deepest)
    first = leafs[0]
    # build ordered list of ancestors for first leaf (nearest first)
    ref_chain = _ancestor_chain(first)
    if not ref_chain:
        return None

    common = set(ref_chain)
    for acc in leafs[1:]:
        common &= set(_ancestor_chain(acc))
        if not common:
            return None

    # choose the deepest (closest to leaves) that is a group account in this company
    for candidate in ref_chain:
        if candidate in common:
            node = _get_account_node(candidate)
            if node.get("company") == company and cint(node.get("is_group")) == 1:
                return candidate

    return None


def _build_summary_chart(periods, currency: str, group_series: dict, section_labels: list[str]):
    """Build a bar chart using the rolled-up series for each group; only used in Summary mode."""
    labels = [p["label"] for p in periods]
    datasets = [{"name": label, "values": group_series.get(label, [0.0] * len(labels))} for label in section_labels]
    colors = ["#B77466", "#FFE1AF", "#E2B59A", "#957C62", "#F4F4F4", "#34495E"]
    return {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "colors": colors[:len(datasets)],
        "custom_options": json.dumps({
            "tooltip": {"fieldtype": "Currency", "options": currency, "always_show_decimals": False},
            "axisOptions": {"shortenYAxisNumbers": 1}
        }),
        "fieldtype": "Currency",
        "options": currency,
    }