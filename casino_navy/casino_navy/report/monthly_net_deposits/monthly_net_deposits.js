// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Monthly Net Deposits"] = {
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
			"fieldname": "presentation_currency",
			"label": __("Presentation Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"default": frappe.defaults.get_user_default("Currency"),
			"reqd": 1
		},
		{
			"fieldname": "fiscal_year",
			"label": __("Fiscal Year"),
			"fieldtype": "Link",
			"options": "Fiscal Year",
			"default": "2025",
			"reqd": 1
		},
		{
			"fieldname": "summary",
			"label": __("Summary"),
			"fieldtype": "Check",
			"default": 1
		},

	]
};
