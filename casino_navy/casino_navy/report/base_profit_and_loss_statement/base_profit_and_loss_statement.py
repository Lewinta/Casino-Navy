# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.report.financial_statements import (
	get_columns,
	filter_accounts,
	get_appropriate_currency,
	calculate_values,
	prepare_data,
	add_total_row,
	apply_additional_conditions,
	filter_out_zero_value_rows,
	accumulate_values_into_parents,
	get_filtered_list_for_consolidated_report,
	get_period_list,
)


def execute(filters=None):
	period_list = get_period_list(
		filters.from_fiscal_year,
		filters.to_fiscal_year,
		filters.period_start_date,
		filters.period_end_date,
		filters.filter_based_on,
		filters.periodicity,
		company=filters.company,
	)
	if not filters.get("presentation_currency"):
		frappe.throw(
			_("Please select a Presentation Currency to view the report."),
			title=_("Missing Presentation Currency"),
		)
	income = get_data(
		filters.company,
		"Income",
		"Credit",
		period_list,
		filters=filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True,
		ignore_accumulated_values_for_fy=True,
	)

	expense = get_data(
		filters.company,
		"Expense",
		"Debit",
		period_list,
		filters=filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True,
		ignore_accumulated_values_for_fy=True,
	)

	net_profit_loss = get_net_profit_loss(
		income, expense, period_list, filters.company, filters.presentation_currency
	)

	data = []
	data.extend(income or [])
	data.extend(expense or [])
	if net_profit_loss:
		data.append(net_profit_loss)

	columns = get_columns(
		filters.periodicity, period_list, filters.accumulated_values, filters.company
	)

	chart = get_chart_data(filters, columns, income, expense, net_profit_loss)

	currency = filters.presentation_currency or frappe.get_cached_value(
		"Company", filters.company, "default_currency"
	)
	report_summary = get_report_summary(
		period_list, filters.periodicity, income, expense, net_profit_loss, currency, filters
	)

	return columns, data, None, chart, report_summary

def get_accounts(company, root_type):
	return frappe.db.sql(
		"""
		select name, account_number, parent_account, lft, rgt, root_type, report_type, account_name, include_in_gross, account_type, is_group, lft, rgt
		from `tabAccount`
		where company=%s and root_type=%s order by lft""",
		(company, root_type),
		as_dict=True,
	)


def set_gl_entries_by_account(
	company,
	from_date,
	to_date,
	root_lft,
	root_rgt,
	filters,
	gl_entries_by_account,
	ignore_closing_entries=False,
	ignore_opening_entries=False,
	root_type=None,
):
	"""Returns a dict like { "account": [gl entries], ... }"""
	gl_entries = []

	account_filters = {
		"company": company,
		"is_group": 0,
		"lft": (">=", root_lft),
		"rgt": ("<=", root_rgt),
	}

	if root_type:
		account_filters.update(
			{
				"root_type": root_type,
			}
		)

	accounts_list = frappe.db.get_all(
		"Account",
		filters=account_filters,
		pluck="name",
	)

	if accounts_list:
		# For balance sheet
		ignore_closing_balances = frappe.db.get_single_value(
			"Accounts Settings", "ignore_account_closing_balance"
		)
		if not from_date and not ignore_closing_balances:
			last_period_closing_voucher = frappe.db.get_all(
				"Period Closing Voucher",
				filters={
					"docstatus": 1,
					"company": filters.company,
					"posting_date": ("<", filters["period_start_date"]),
				},
				fields=["posting_date", "name"],
				order_by="posting_date desc",
				limit=1,
			)
			if last_period_closing_voucher:
				gl_entries += get_accounting_entries(
					"Account Closing Balance",
					from_date,
					to_date,
					accounts_list,
					filters,
					ignore_closing_entries,
					last_period_closing_voucher[0].name,
				)
				from_date = add_days(last_period_closing_voucher[0].posting_date, 1)
				ignore_opening_entries = True

		gl_entries += get_accounting_entries(
			"GL Entry",
			from_date,
			to_date,
			accounts_list,
			filters,
			ignore_closing_entries,
			ignore_opening_entries=ignore_opening_entries,
		)

		for entry in gl_entries:
			gl_entries_by_account.setdefault(entry.account, []).append(entry)

		return gl_entries_by_account


def get_accounting_entries(
	doctype,
	from_date,
	to_date,
	accounts,
	filters,
	ignore_closing_entries,
	period_closing_voucher=None,
	ignore_opening_entries=False,
):
	gl_entry = frappe.qb.DocType(doctype)
	query = (
		frappe.qb.from_(gl_entry)
		.select(
			gl_entry.account,
			gl_entry.debit,
			gl_entry.credit,
			gl_entry.debit_in_account_currency,
			gl_entry.credit_in_account_currency,
			gl_entry.account_currency,
		)
		.where(gl_entry.company == filters.company)
	)

	if doctype == "GL Entry":
		query = query.select(gl_entry.posting_date, gl_entry.is_opening, gl_entry.fiscal_year)
		query = query.where(gl_entry.is_cancelled == 0)
		query = query.where(gl_entry.posting_date <= to_date)

		if ignore_opening_entries:
			query = query.where(gl_entry.is_opening == "No")
	else:
		query = query.select(gl_entry.closing_date.as_("posting_date"))
		query = query.where(gl_entry.period_closing_voucher == period_closing_voucher)

	query = apply_additional_conditions(doctype, query, from_date, ignore_closing_entries, filters)
	query = query.where(
		(gl_entry.account.isin(accounts))&
		(gl_entry.account_currency == filters.presentation_currency)
	)

	entries = query.run(as_dict=True)

	return entries

def calculate_account_currency_values(
	accounts_by_name,
	gl_entries_by_account,
	period_list,
	accumulated_values,
	ignore_accumulated_values_for_fy,
):
	for entries in gl_entries_by_account.values():
		for entry in entries:
			d = accounts_by_name.get(entry.account)
			if not d:
				frappe.throw(_("Could not retrieve account {0}").format(entry.account))
			for period in period_list:
				if entry.posting_date <= period.to_date:
					if (accumulated_values or entry.posting_date >= period.from_date) and (
						not ignore_accumulated_values_for_fy or entry.fiscal_year == period.to_date_fiscal_year
					):
						d[period.key] = d.get(period.key, 0.0) + flt(entry.debit_in_account_currency) - flt(
							entry.credit_in_account_currency
						)

			if entry.posting_date < period_list[0].year_start_date:
				d["opening_balance"] = d.get("opening_balance", 0.0) + flt(
					entry.debit_in_account_currency
				) - flt(entry.credit_in_account_currency)


def get_data(
	company,
	root_type,
	balance_must_be,
	period_list,
	filters=None,
	accumulated_values=1,
	only_current_fiscal_year=True,
	ignore_closing_entries=False,
	ignore_accumulated_values_for_fy=False,
	total=True,
):

	accounts = get_accounts(company, root_type)
	if not accounts:
		return None

	accounts, accounts_by_name, parent_children_map = filter_accounts(accounts)

	company_currency = filters.get("presentation_currency") or frappe.get_cached_value(
		"Company", company, "default_currency"
	)

	gl_entries_by_account = {}
	for root in frappe.db.sql(
		"""select lft, rgt from tabAccount
			where root_type=%s and ifnull(parent_account, '') = ''""",
		root_type,
		as_dict=1,
	):

		set_gl_entries_by_account(
			company,
			period_list[0]["year_start_date"] if only_current_fiscal_year else None,
			period_list[-1]["to_date"],
			root.lft,
			root.rgt,
			filters,
			gl_entries_by_account,
			ignore_closing_entries=ignore_closing_entries,
			root_type=root_type,
		)

	calculate_account_currency_values(
		accounts_by_name,
		gl_entries_by_account,
		period_list,
		accumulated_values,
		ignore_accumulated_values_for_fy,
	)

	accumulate_values_into_parents(accounts, accounts_by_name, period_list)
	out = prepare_data(accounts, balance_must_be, period_list, company_currency)
	out = filter_out_zero_value_rows(out, parent_children_map)

	if out and total:
		add_total_row(out, root_type, balance_must_be, period_list, company_currency)

	return out


def get_report_summary(
	period_list, periodicity, income, expense, net_profit_loss, currency, filters, consolidated=False
):
	net_income, net_expense, net_profit = 0.0, 0.0, 0.0

	# from consolidated financial statement
	if filters.get("accumulated_in_group_company"):
		period_list = get_filtered_list_for_consolidated_report(filters, period_list)

	for period in period_list:
		key = period if consolidated else period.key
		if income:
			net_income += income[-2].get(key)
		if expense:
			net_expense += expense[-2].get(key)
		if net_profit_loss:
			net_profit += net_profit_loss.get(key)

	if len(period_list) == 1 and periodicity == "Yearly":
		profit_label = _("Profit This Year")
		income_label = _("Total Income This Year")
		expense_label = _("Total Expense This Year")
	else:
		profit_label = _("Net Profit")
		income_label = _("Total Income")
		expense_label = _("Total Expense")

	return [
		{"value": net_income, "label": income_label, "datatype": "Currency", "currency": currency},
		{"type": "separator", "value": "-"},
		{"value": net_expense, "label": expense_label, "datatype": "Currency", "currency": currency},
		{"type": "separator", "value": "=", "color": "blue"},
		{
			"value": net_profit,
			"indicator": "Green" if net_profit > 0 else "Red",
			"label": profit_label,
			"datatype": "Currency",
			"currency": currency,
		},
	]


def get_net_profit_loss(income, expense, period_list, company, currency=None, consolidated=False):
	total = 0
	net_profit_loss = {
		"account_name": "'" + _("Profit for the year") + "'",
		"account": "'" + _("Profit for the year") + "'",
		"warn_if_negative": True,
		"currency": currency or frappe.get_cached_value("Company", company, "default_currency"),
	}

	has_value = False

	for period in period_list:
		key = period if consolidated else period.key
		total_income = flt(income[-2][key], 3) if income else 0
		total_expense = flt(expense[-2][key], 3) if expense else 0

		net_profit_loss[key] = total_income - total_expense

		if net_profit_loss[key]:
			has_value = True

		total += flt(net_profit_loss[key])
		net_profit_loss["total"] = total

	if has_value:
		return net_profit_loss


def get_chart_data(filters, columns, income, expense, net_profit_loss):
	labels = [d.get("label") for d in columns[2:]]

	income_data, expense_data, net_profit = [], [], []

	for p in columns[2:]:
		if income:
			income_data.append(income[-2].get(p.get("fieldname")))
		if expense:
			expense_data.append(expense[-2].get(p.get("fieldname")))
		if net_profit_loss:
			net_profit.append(net_profit_loss.get(p.get("fieldname")))

	datasets = []
	if income_data:
		datasets.append({"name": _("Income"), "values": income_data})
	if expense_data:
		datasets.append({"name": _("Expense"), "values": expense_data})
	if net_profit:
		datasets.append({"name": _("Net Profit/Loss"), "values": net_profit})

	chart = {"data": {"labels": labels, "datasets": datasets}}

	if not filters.accumulated_values:
		chart["type"] = "bar"
	else:
		chart["type"] = "line"

	chart["fieldtype"] = "Currency"

	return chart
