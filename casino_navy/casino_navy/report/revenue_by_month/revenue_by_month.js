// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Revenue By Month"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname": "fiscal_year",
			"label": __("Fiscal Year"),
			"fieldtype": "Link",
			"options": "Fiscal Year",
			"default": '2025',
			"reqd": 1
		},
		{
			"fieldname": "account",
			"label": __("Account"),
			"fieldtype": "Link",
			"options": "Account",
			"default": '40000 - INCOME / REVENUE - X2',
			"reqd": 1
		},
		{
			"fieldname": "group_accounts",
			"label": __("Group Accounts"),
			"fieldtype": "Check",
			"default": 0
		}
	]
};
