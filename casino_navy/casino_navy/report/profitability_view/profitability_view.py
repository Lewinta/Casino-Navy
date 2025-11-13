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
    fiscal_year = filters.get("fiscal_year")
    companies = filters.get("company")

    if not companies or not fiscal_year:
        return [], [], None, None

    if isinstance(companies, str):
        companies = [c.strip() for c in companies.split(",") if c.strip()]

    sort_order_map = _get_global_section_order(REPORT_NAME)

    first_company = companies[0]
    currency = frappe.db.get_value("Company", first_company, "default_currency") or "USD"

    fy_start, fy_end = _get_fiscal_year_dates(fiscal_year)
    periods = _build_month_periods(fy_start, fy_end)
    key_index = {p["key"]: idx for idx, p in enumerate(periods)}
    n = len(periods)

    section_series = {}
    all_section_labels = set()

    for company in companies:
        sections = _load_sections_from_mapper(REPORT_NAME, company)
        resolved = _resolve_sections_leafs(company, sections)
        all_section_labels.update(resolved.keys())

        all_leafs = sorted({
            leaf for info in resolved.values()
            for leaf in (info.get("leafs") or [])
            if leaf
        })
        if not all_leafs:
            continue

        month_sums = _get_monthly_debit_credit(company, fy_start, fy_end, all_leafs)

        normalized_series = {}
        for lbl, vals in section_series.items():
            norm_lbl = _normalize_label(lbl)
            normalized_series[norm_lbl] = vals
        section_series = normalized_series
        all_section_labels = set(section_series.keys())

        for label, info in resolved.items():
            if label not in section_series:
                section_series[label] = [0.0] * n
            for acc in sorted([a for a in (info.get("leafs") or []) if a]):
                sign = info["signs"].get(acc, 1)
                for k, sums in (month_sums.get(acc) or {}).items():
                    if k not in key_index:
                        continue
                    i = key_index[k]
                    debit = float(sums.get("debit") or 0.0)
                    credit = float(sums.get("credit") or 0.0)
                    net = credit - debit
                    section_series[label][i] += sign * net
        
        # Normalize labels to ensure clean formula resolution
        section_series = {_normalize_label(k): v for k, v in section_series.items()}
        all_section_labels = set(section_series.keys())

        # Build unified formula list from all companies’ mappers
        all_formulas = {}
        for company in companies:
            sections = _load_sections_from_mapper(REPORT_NAME, company)
            resolved = _resolve_sections_leafs(company, sections)
            for label, info in resolved.items():
                formulas = info.get("formulas") or []
                if formulas:
                    all_formulas[label] = formulas

        # Evaluate each formula label once, using all collected bucket data
        for label, formulas in all_formulas.items():
            out = [0.0] * n
            for i in range(n):
                ctx = {k: section_series.get(k, [0] * n)[i] for k in all_section_labels}
                out[i] = _evaluate_formulas(ctx, formulas)
            section_series[label] = out
            all_section_labels.add(label)


    data = []
    for label in sorted(all_section_labels, key=lambda lbl: sort_order_map.get(lbl, 9999)):
        values = section_series.get(label, [0.0] * n)
        total = sum(values)

        is_formula = label in all_formulas

        row = {
            "account": label,
            "account_name": label,
            "currency": currency,
            "total": total,
            "is_formula": 1 if is_formula else 0, 
        }

        for p, v in zip(periods, values):
            row[p["key"]] = v

        data.append(row)

    columns = _build_columns(periods)

    chart = _build_chart(
        rows=data,
        periods=periods,
        currency=currency,
        colors=["#2563eb", "#ef4444", "#16a34a"]
    )

    return columns, data, None, chart
# -------------------------- helpers --------------------------

from functools import lru_cache

def _normalize_label(label: str) -> str:
    """Normalize label for consistent formula resolution."""
    return re.sub(r"\s+", " ", (label or "").strip())

def _get_global_section_order(report_name):
    """
    Returns a dict {section_label: sort_order}, aggregating from all companies
    in the Accountant Mapper for the given report.
    Sections without a sort_order will get a high number (so they go last).
    """
    result = frappe.db.sql(
        """
        SELECT amd.section_label, MIN(amd.sort_order) AS sort_order
        FROM `tabAccountant Mapper Item` amd
        JOIN `tabAccountant Mapper` am ON am.name = amd.parent
        WHERE am.report = %s
        GROUP BY amd.section_label
        ORDER BY MIN(amd.sort_order)
        """,
        (report_name,),
        as_dict=True,
    )

    order_map = {}
    for r in result:
        order_map[r["section_label"]] = int(r["sort_order"] or 9999)
    return order_map

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
    # direct label match to an Account in this company
    if frappe.db.exists("Account", {"name": section_label, "company": company}):
        return section_label
    if not leafs:
        return None
    # deepest common ancestor of all leafs
    ref_chain = _ancestor_chain(leafs[0])
    common = set(ref_chain)
    for acc in leafs[1:]:
        common &= set(_ancestor_chain(acc))
        if not common:
            return None
    for candidate in ref_chain:        # nearest first
        node = _get_account_node(candidate)
        if candidate in common and node.get("company") == company and node.get("is_group") == 1:
            return candidate
    return None

def _make_row_payload(
    account: str,              # real Account (clickable) or "" (non-clickable)
    display_label: str,        # shows in Account column
    periods, values: list[float],
    currency: str,
    year_start, year_end,
    parent_account: str = "",
    account_type: str = "",
    bold: int = 1,
):
    row = {
        "account": account,
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
        periods.append({
            "key": key, "label": label,
            "from": cur, "to": date(cur.year, cur.month, last_day)
        })
        cur = (cur + relativedelta(months=1)).replace(day=1)
    return periods


def _build_columns(periods):
    cols = [
        {
            "label": "Bucket",
            "fieldname": "account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 260,
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
            AND gle.posting_date >= '2025-06-01'
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
    Evaluate formulas like {"formula": "Revenue X2 - Total Expenses X2"}
    against dict keys that may include multiple companies.
    """
    import re

    # Normalize all keys once
    normalized = { _normalize_label(k): v for k, v in section_totals_for_period.items() }
    total = 0.0

    for f in formulas or []:
        expr = (f.get("formula") or "").strip()
        if not expr:
            continue

        safe = expr
        for lbl, val in normalized.items():
            # Replace normalized label (case-insensitive, word-boundary safe)
            safe = re.sub(rf"(?i)\b{re.escape(lbl)}\b", str(val), safe)

        # Guardrail: only digits, operators, decimal points, parentheses, and spaces
        if re.search(r"[^0-9\.\+\-\*\/\(\) ]", safe):
            continue

        try:
            val = eval(safe) if safe.strip() else 0.0
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