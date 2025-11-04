// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.require("assets/erpnext/js/financial_statements.js", function () {
  frappe.query_reports["Net Profit Line Summary"] = {
    filters: [
      {
        fieldname: "company",
        label: __("Company"),
        fieldtype: "Link",
        options: "Company",
        default: frappe.defaults.get_user_default("Company"),
        reqd: 1,
        onchange() {
          frappe.query_report?.refresh();
        },
      },
      {
        fieldname: "fiscal_year",
        label: __("Fiscal Year"),
        fieldtype: "Link",
        options: "Fiscal Year",
        default: "2025",
        reqd: 1,
      },
    ],
    // make first column clickable like FS
    formatter: erpnext.financial_statements.formatter,
    tree: false,
    name_field: "account",
    parent_field: "parent_account",
    initial_depth: 1,
    onload(report) { /* nothing else needed */ },
  };
});

// --- FINAL, SCOPED PATCH: ensure the report chart uses the currency sent by the server (EUR) ---
frappe.ready(() => {
  if (frappe.__npls_currency_patch__) return;
  frappe.__npls_currency_patch__ = true;

  const orig_make_chart = frappe.utils.make_chart;

  frappe.utils.make_chart = function (parent, args) {
    try {
      // Only touch our report’s chart
      if (frappe.query_report && frappe.query_report.report_name === "Net Profit Line Summary") {
        // Prefer the currency the server (Python) already sent as chart.options
        // (your .py sets chart["options"] = company_currency)
        let currency =
          (args && args.options) ||
          // secondary: try to read from custom_options.tooltip.options if present
          (() => {
            try {
              const co = args && args.custom_options ? JSON.parse(args.custom_options) : null;
              return co && co.tooltip && co.tooltip.options;
            } catch (e) { return null; }
          })() ||
          // last resort fallback
          "EUR";

        // Force Currency type and inject a real formatter function (JSON cannot carry functions)
        args = args || {};
        args.fieldtype = "Currency";
        args.options = currency;
        args.tooltipOptions = {
          formatTooltipY: (val) =>
            frappe.format(val, { fieldtype: "Currency" }, { inline: true, currency }),
        };

        // Keep axis options tidy without wiping anything else
        args.axisOptions = Object.assign({ shortenYAxisNumbers: 1 }, args.axisOptions || {});

        // Debug once if you need:
        console.log("[NPLS] Chart currency used:", currency);
      }
    } catch (e) {
      // swallow and continue with original
    }
    return orig_make_chart.call(this, parent, args);
  };
});