// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */


frappe.require("assets/erpnext/js/financial_statements.js", function() {
	frappe.query_reports["Cash Balance"] = {
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
				"default": "2025",
				"reqd": 1
			},
			{
				"fieldname": "summary",
				"label": __("Summary"),
				"fieldtype": "Check",
				"default": 1
			},
		],
		"formatter": erpnext.financial_statements.formatter,
		"tree": true,
		"name_field": "account",
		"parent_field": "parent_account",
		"initial_depth": 3,
	};
	erpnext.utils.add_dimensions('Cash Balance', 6);
});