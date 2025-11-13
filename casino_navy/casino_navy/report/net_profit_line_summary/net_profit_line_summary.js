// Copyright (c) 2025, Lewin Villar and contributors
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

    formatter(value, row, column, data, default_formatter) {
      value = default_formatter(value, row, column, data);
      if (column.fieldname === "account" && data && data.account) {
        value = `<a href="#" class="grey"
          onclick="frappe.query_reports['Net Profit Line Summary'].open_general_ledger('${encodeURIComponent(
            data.account
          )}'); return false;">${value}</a>`;
      }
      return value;
    },

    open_general_ledger(section_label) {
      section_label = decodeURIComponent(section_label);
      const company = frappe.query_report.get_filter_value("company");
      const fiscal_year = frappe.query_report.get_filter_value("fiscal_year");

      frappe.call({
        method: "casino_navy.utils.get_accounts_for_section",
        args: { company, section_label, report_name: "Net Profit Line Summary" },
        freeze: true,
        freeze_message: __("Loading mapped accounts..."),
        callback: function (r) {
          const accounts = r.message.accounts || [];

          if (!accounts.length) {
            frappe.msgprint(__("No mapped accounts found for section: {0}", [section_label]));
            return;
          }

          // Get fiscal year dates before routing to GL
          frappe.db
            .get_value("Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"])
            .then((res) => {
              const fy = res.message;
              frappe.route_options = {
                company,
                account: accounts,
                from_date: fy.year_start_date,
                to_date: fy.year_end_date,
              };
              frappe.set_route("query-report", "General Ledger");
            });
        },
      });
    },
    onload(report) {
      // Hook into refresh AFTER data is loaded
      const original_refresh = report.refresh;

      report.refresh = async function () {
        await original_refresh.call(this);

        try {
          // Frappe stores the executed report response here
          const resp =
            frappe.query_report.last_response ||
            frappe.query_report.data ||
            {};

          // Safely traverse to message.message.accounts_by_section
          let meta = null;

          if (
            resp.message &&
            resp.message.message &&
            resp.message.message.accounts_by_section
          ) {
            meta = resp.message.message;
          } else if (
            resp.message &&
            resp.message.accounts_by_section
          ) {
            meta = resp.message;
          }

          if (meta && meta.accounts_by_section) {
            frappe.query_report.data_meta = meta;
            console.log("[NPLS] Loaded accounts_by_section:", meta.accounts_by_section);
          } else {
            console.warn("[NPLS] No accounts_by_section found; resp:", resp);
          }
        } catch (e) {
          console.warn("[NPLS] meta extraction failed:", e);
        }
      };
    },
  };
});

// --- Chart currency patch (execute immediately, not inside frappe.ready) ---
if (!frappe.__npls_currency_patch__) {
  frappe.__npls_currency_patch__ = true;

  const orig_make_chart = frappe.utils.make_chart;
  frappe.utils.make_chart = function (parent, args) {
    try {
      if (frappe.query_report && frappe.query_report.report_name === "Net Profit Line Summary") {
        let currency =
          (args && args.options) ||
          (() => {
            try {
              const co = args && args.custom_options ? JSON.parse(args.custom_options) : null;
              return co && co.tooltip && co.tooltip.options;
            } catch (e) {
              return null;
            }
          })() ||
          "USD";

        args = args || {};
        args.fieldtype = "Currency";
        args.options = currency;
        args.tooltipOptions = {
          formatTooltipY: (val) =>
            frappe.format(val, { fieldtype: "Currency" }, { inline: true, currency }),
        };
        args.axisOptions = Object.assign({ shortenYAxisNumbers: 1 }, args.axisOptions || {});
      }
    } catch (e) {}
    return orig_make_chart.call(this, parent, args);
  };
}