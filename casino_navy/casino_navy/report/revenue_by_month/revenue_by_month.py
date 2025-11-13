# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import json
import frappe
import calendar
from frappe import _
from datetime import date
from functools import lru_cache
from dateutil.relativedelta import relativedelta
from frappe.utils.nestedset import get_descendants_of

def execute(filters=None):
	if not filters:
		filters = {}

	company = filters.get("company")
	fiscal_year = filters.get("fiscal_year")
	account = filters.get("account")
	group_flag = _as_bool(filters.get("group_accounts"))

	_validate_required(company, fiscal_year, account)

	fy_start, fy_end = _get_fiscal_year_dates(fiscal_year)
	periods = _build_month_periods(fy_start, fy_end)  # [{key,label,from,to}, ...]
	period_index_by_key = {p["key"]: idx for idx, p in enumerate(periods)}

	# Company currency
	currency = frappe.db.get_value("Company", company, "default_currency") or "USD"

	# Is selected account a group?
	is_group = bool(frappe.db.get_value("Account", account, "is_group"))

	data = []

	if group_flag and is_group:
		# ---- GROUP MODE: roll-up all descendants into the parent row ----
		leaf_accounts = _resolve_accounts(company, account)  # leafs under the parent
		amounts = _get_monthly_amounts(company, fy_start, fy_end, leaf_accounts)

		# aggregate per month across all leaf accounts
		agg_per_month = _aggregate_amounts_by_period(amounts)

		month_vals = [0.0] * len(periods)
		for k, amt in agg_per_month.items():
			if k in period_index_by_key:
				month_vals[period_index_by_key[k]] = amt

		row_total = sum(month_vals)
		if row_total != 0:
			meta = _get_account_meta(account)
			row = {
				"account": account,                           
				"account_name": meta["account_name"] or account,
				"parent_account": meta["parent_account"] or "",
				"account_type": meta["account_type"] or "",
				"year_start_date": fy_start,                  
				"year_end_date": fy_end,
				"from_date": fy_start,                        
				"to_date": fy_end,
				"currency": currency,
			}
			for i, p in enumerate(periods):
				row[p["key"]] = month_vals[i]
			row["total"] = row_total
			data.append(row)

		# Chart uses ONLY the parent (rolled-up) account
		display_map = _get_account_display_names(company, [account])
		chart = _build_chart(data, periods, currency=currency, top_n=1, display_map=display_map)

	else:
		# ---- DETAIL MODE: show each leaf account as a row/dataset ----
		rows_accounts = _resolve_accounts(company, account)  # if parent, returns leafs; else [account]
		amounts = _get_monthly_amounts(company, fy_start, fy_end, rows_accounts)

		for acc in rows_accounts:
			month_vals = [0.0] * len(periods)
			if acc in amounts:
				for k, amt in amounts[acc].items():
					if k in period_index_by_key:
						month_vals[period_index_by_key[k]] = amt

			row_total = sum(month_vals)
			if row_total == 0:
				continue

			meta = _get_account_meta(acc)
			row = {
				"account": acc,                                   # 👈 clickable (leaf)
				"account_name": meta["account_name"] or acc,
				"parent_account": meta["parent_account"] or "",
				"account_type": meta["account_type"] or "",
				"year_start_date": fy_start,
				"year_end_date": fy_end,
				"from_date": fy_start,
				"to_date": fy_end,
				"currency": currency,
			}
			for i, p in enumerate(periods):
				row[p["key"]] = month_vals[i]
			row["total"] = row_total
			data.append(row)

		display_map = _get_account_display_names(company, rows_accounts)
		chart = _build_chart(data, periods, currency=currency, top_n=10, display_map=display_map)

	columns = _build_columns(periods)
	return columns, data, None, chart


# --------------------------
# Helpers
# --------------------------

@lru_cache(maxsize=None)
def _get_account_meta(account_name: str):
    if not account_name:
        return {"account_name": account_name, "parent_account": None, "account_type": None}
    row = frappe.db.get_value(
        "Account",
        account_name,
        ["account_name", "parent_account", "account_type"],
        as_dict=True,
    ) or {}
    return {
        "account_name": row.get("account_name") or account_name,
        "parent_account": row.get("parent_account"),
        "account_type": row.get("account_type"),
    }

def _as_bool(v):
	"""Normalize truthy values coming from report filters."""
	return str(v).lower() in {"1", "true", "yes", "y", "on"}


def _aggregate_amounts_by_period(amounts_by_account):
	"""Input: {account: {'YYYY-MM': amount, ...}, ...}
	   Output: {'YYYY-MM': summed_amount}"""
	out = {}
	for acc_map in (amounts_by_account or {}).values():
		for period_key, amt in (acc_map or {}).items():
			out[period_key] = out.get(period_key, 0.0) + float(amt or 0)
	return out


def _build_chart(data_rows, periods, currency="USD", top_n=10, display_map=None):
	"""Return a Frappe report chart: grouped bars with months on X, one dataset per account."""
	if not data_rows:
		return None

	display_map = display_map or {}

	# Sort by Total desc and keep top N accounts to avoid overcrowding the chart
	top = sorted(data_rows, key=lambda r: r.get("total", 0), reverse=True)[:top_n]

	labels = [p["label"] for p in periods]  # e.g., ["Jan 25", "Feb 25", ...]
	datasets = []
	for r in top:
		values = [r.get(p["key"], 0) for p in periods]
		disp = display_map.get(r["account"], r["account"])  # clean name for legend/tooltip
		datasets.append({
			"name": disp,
			"values": values
		})

	chart = {
		"type": "bar",
		"data": {
			"labels": labels,
			"datasets": datasets,
		},
		# Optional chart options
		"barOptions": {
			"stacked": 0  # set to 1 if you prefer stacked bars
		},

		# Let the renderer know how to format values
		"fieldtype": "Currency",
		"options": currency,

		# Mirror dashboard 'custom_options' so report chart tooltips/y-axis match
		"custom_options": json.dumps({
			"tooltip": {
				"fieldtype": "Currency",
				"options": currency,
				"always_show_decimals": False
			},
			"axisOptions": {
				"shortenYAxisNumbers": 1
			}
		})
	}
	return chart


def _get_account_display_names(company, accounts):
	"""Return {account_full_name: clean_display_name} using Account.account_name
	(which has no number/abbr). Falls back to a smart strip."""
	if not accounts:
		return {}

	rows = frappe.get_all(
		"Account",
		filters={"name": ["in", accounts]},
		fields=["name", "account_name", "account_number", "company"],
	)
	abbr = frappe.db.get_value("Company", company, "abbr") or ""

	display = {}
	for r in rows:
		name = r.get("name")
		acc_name = (r.get("account_name") or "").strip()
		if acc_name:
			display[name] = acc_name
			continue

		# Fallback: strip patterns like "1010 - Cash - ABC" or "Cash - ABC"
		raw = name or ""
		parts = [p.strip() for p in raw.split(" - ") if p.strip()]
		if parts:
			# drop trailing company abbr
			if abbr and parts[-1] == abbr:
				parts = parts[:-1]
			# drop leading numeric code
			if parts and parts[0].replace(" ", "").replace("-", "").isdigit():
				parts = parts[1:]
		display[name] = " - ".join(parts) if parts else raw

	return display


def _validate_required(company, fiscal_year, account):
	missing = [n for n, v in [("company", company), ("fiscal_year", fiscal_year), ("account", account)] if not v]
	if missing:
		frappe.throw(_("Missing filters: {0}").format(", ".join(missing)))


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
		month_last_day = calendar.monthrange(cur.year, cur.month)[1]
		from_dt = cur
		to_dt = date(cur.year, cur.month, month_last_day)
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
            "width": 320,
            "align": "left",   # ensure left-aligned
        },
        # hidden helpers used by the formatter / GL routing
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


def _resolve_accounts(company: str, chosen_account: str):
	"""If chosen account is a group, return all **leaf** descendant accounts.
	   Otherwise return [chosen_account]. Restricted to the same company."""
	is_group = frappe.db.get_value("Account", chosen_account, "is_group")

	if not is_group:
		return [chosen_account]

	# Get descendants via nested set
	descendants = get_descendants_of("Account", chosen_account)
	if not descendants:
		return []

	# Keep only leaf accounts (is_group = 0) in same company
	leafs = frappe.get_all(
		"Account",
		filters={"name": ["in", descendants], "company": company, "is_group": 0},
		pluck="name",
	)
	# sort by account number if present, else name
	return sorted(leafs, key=lambda n: (frappe.db.get_value("Account", n, "account_number") or "", n))


def _get_monthly_amounts(company: str, from_date: date, to_date: date, accounts):
	"""Return dict: {account: {'YYYY-MM': amount, ...}, ...}
	   Amount uses (credit - debit) so income is positive."""
	if not accounts:
		return {}

	# Single SQL for performance: group by account + month bucket
	placeholders = ", ".join(["%s"] * len(accounts))
	sql = f"""
		SELECT
			gle.account,
			DATE_FORMAT(gle.posting_date, '%%Y-%%m-01') AS period_start,
			SUM(gle.credit - gle.debit) AS amount
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

	result = {}
	for r in rows:
		acc = r["account"]
		# Convert 'YYYY-mm-01' to 'YYYY-mm'
		key = r["period_start"][:7]
		result.setdefault(acc, {})[key] = float(r["amount"] or 0)
	return result