// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.require("assets/erpnext/js/financial_statements.js", function () {
  frappe.query_reports["Revenue By Month"] = {
    onload(report) {
      const fy = frappe.query_report.get_filter_value("fiscal_year");
      if (!fy) return;

      frappe.model.with_doc("Fiscal Year", fy);
    },

    formatter(value, row, column, data, default_formatter) {
      value = default_formatter(value, row, column, data);

      if (column.fieldname === "account" && data && data.account) {
        const account = encodeURIComponent(data.account);
        const label = frappe.utils.escape_html(data.account_name || data.account);

        value = `
          <a href="#" 
             onclick="frappe.query_reports['Revenue By Month'].open_gl('${account}'); 
                      return false;">
             ${label}
          </a>`;
      }

      return value;
    },

    open_gl(account) {
      account = decodeURIComponent(account);

      const company = frappe.query_report.get_filter_value("company");
      const fy = frappe.query_report.get_filter_value("fiscal_year");

      frappe.db.get_value("Fiscal Year", fy, ["year_start_date", "year_end_date"])
        .then(res => {
          const fy_dates = res.message || {};

          frappe.route_options = {
            company,
            account,
            from_date: fy_dates.year_start_date,
            to_date: fy_dates.year_end_date
          };

          frappe.set_route("query-report", "General Ledger");
        });
    },

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