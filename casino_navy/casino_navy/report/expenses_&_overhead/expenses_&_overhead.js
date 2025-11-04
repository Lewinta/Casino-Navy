// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.require("assets/erpnext/js/financial_statements.js", function () {
  frappe.query_reports["Expenses & Overhead"] = {
    filters: [
      {
        fieldname: "company",
        label: __("Company"),
        fieldtype: "Link",
        options: "Company",
        default: frappe.defaults.get_user_default("Company"),
        reqd: 1,
      },
      {
        fieldname: "fiscal_year",
        label: __("Fiscal Year"),
        fieldtype: "Link",
        options: "Fiscal Year",
        default: frappe.defaults.get_user_default("fiscal_year"),
        reqd: 1,
      },
    ],

    // Make the first column clickable like core financial statements
    formatter: erpnext.financial_statements.formatter,

    // Flat list (buckets only). If you later add parent_account, you can turn this on.
    tree: false,
    name_field: "account",
    parent_field: "parent_account",
    initial_depth: 1,

    onload(report) {}
  };
});