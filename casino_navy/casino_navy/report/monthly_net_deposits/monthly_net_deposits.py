# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import frappe
from frappe import qb
from frappe.query_builder import Criterion, Case, functions as fn

def execute(filters=None):
	return get_columns(filters), get_data(filters)

def get_columns(filters):
	if filters and filters.get("summary"):
		return [
			{
				"fieldname": "company",
				"label": "Company",
				"fieldtype": "Link",
				"options": "Company",
				"width": 200,
			},
			{
				"fieldname": "deposit",
				"label": "Total Deposit",
				"fieldtype": "Currency",
				"width": 180,
			},
			{
				"fieldname": "withdraw",
				"label": "Total Withdraw",
				"fieldtype": "Currency",
				"width": 180,
			},
			{
				"fieldname": "net_deposit",
				"label": "Net Deposit",
				"fieldtype": "Currency",
				"width": 200,
			},
		]
	else:
		return [
			{
				"fieldname": "date",
				"label": "Date",
				"fieldtype": "Date",
				"width": 120,
			},
			{
				"fieldname": "transaction_type",
				"label": "Transaction Type",
				"fieldtype": "Data",
				"width": 150,
			},
			{
				"fieldname": "bank",
				"label": "Bank Account / PSP",
				"fieldtype": "Link",
				"options": "Bank Account",
				"width": 200,
			},
			{
				"fieldname": "deposit",
				"label": "Deposit",
				"fieldtype": "Currency",
				"width": 120,
			},
			{
				"fieldname": "withdraw",
				"label": "Withdraw",
				"fieldtype": "Currency",
				"width": 120,
			}
		]

def get_data(filters):
	TL = frappe.qb.DocType("Transaction Ledger")
	# let's get the year start and end dates from the fiscal year
	fy = frappe.get_doc("Fiscal Year", filters.get("fiscal_year"))
	year_start_date = fy.year_start_date
	year_end_date = fy.year_end_date
	conditions = [
		TL.docstatus == 1,
		TL.date[year_start_date : year_end_date]
	]
	if filters.get("summary"):
		
		return qb.from_(TL).select(
			TL.company,
			fn.Sum(
				Case().when(TL.transaction_type == "Deposit", TL.amount).else_(0)
			).as_("deposit"),
			fn.Sum(
				Case().when(TL.transaction_type == "Withdraw", TL.amount).else_(0)
			).as_("withdraw"),
			(fn.Sum(
				Case().when(TL.transaction_type == "Deposit", TL.amount).else_(0)
			) - fn.Sum(
				Case().when(TL.transaction_type == "Withdraw", TL.amount).else_(0)
			)).as_("net_deposit")
		).where(
			Criterion.all(conditions)
		).run(as_dict=1)
	else:
		return qb.from_(TL).select(
			TL.date,
			TL.transaction_type,
			TL.bank,
			Case().when(TL.transaction_type == "Deposit", TL.amount).else_(0).as_("deposit"),
			Case().when(TL.transaction_type == "Withdraw", TL.amount).else_(0).as_("withdraw")
		).where(
			Criterion.all(conditions)
		).orderby(TL.date).run(as_dict=1)

