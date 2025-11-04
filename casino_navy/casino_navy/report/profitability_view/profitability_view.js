// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */
frappe.require("assets/erpnext/js/financial_statements.js", function () {
  frappe.query_reports["Profitability View"] = {
    filters: [
      {
        fieldname: "company",
        label: __("Company"),
        fieldtype: "Link",
        options: "Company",
        reqd: 1,
        default: frappe.defaults.get_default("company"),
      },
      {
        fieldname: "fiscal_year",
        label: __("Fiscal Year"),
        fieldtype: "Link",
        options: "Fiscal Year",
        reqd: 1,
        default: frappe.defaults.get_user_default("fiscal_year"),
      },
    ],
    formatter: erpnext.financial_statements.formatter,
    tree: false,
    name_field: "account",
    parent_field: "parent_account",
    initial_depth: 1,
  };
});