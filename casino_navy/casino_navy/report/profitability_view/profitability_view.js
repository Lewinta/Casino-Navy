// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */

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
};