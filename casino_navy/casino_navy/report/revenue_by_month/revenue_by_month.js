// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.require("assets/erpnext/js/financial_statements.js", function () {
  frappe.query_reports["Revenue By Month"] = {
    onload(report) {
      // set FY date range (optional, helps GL route defaults)
      const company = frappe.query_report.get_filter_value("company");
      const fy_name = frappe.query_report.get_filter_value("fiscal_year");
      if (!fy_name) return;

      frappe.model.with_doc("Fiscal Year", fy_name, function () {
        const fy = frappe.model.get_doc("Fiscal Year", fy_name);
        // nothing to set on filters for this report; rows carry dates
        // (GL uses year_start_date/year_end_date/from_date/to_date from the row)
      });
    },

    // 👇 This makes the Account column clickable + bold logic, etc.
    formatter: erpnext.financial_statements.formatter,

    // If you later add parent_account to rows, tree view will indent nicely
    tree: false,
    name_field: "account",
    parent_field: "parent_account",
    initial_depth: 1,

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
        default: "2025",
        reqd: 1,
      },
      {
        fieldname: "account",
        label: __("Account"),
        fieldtype: "Link",
        options: "Account",
        default: "40000 - INCOME / REVENUE - X2",
        reqd: 1,
      },
      {
        fieldname: "group_accounts",
        label: __("Group Accounts"),
        fieldtype: "Check",
        default: 0,
      },
    ],
  };
});