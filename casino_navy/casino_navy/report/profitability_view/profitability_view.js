frappe.require("assets/erpnext/js/financial_statements.js", function () {
  frappe.query_reports["Profitability View"] = {
    filters: [
      {
        fieldname: "company",
        label: __("Company"),
        fieldtype: "MultiSelectList",
        options: "Company",
        reqd: 1,
        default: frappe.defaults.get_user_default("company"),
        get_data(txt) {
          return frappe.db.get_link_options("Company", txt);
        },
        onchange() {
          frappe.query_report?.refresh();
        },
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

    // Inject a tiny style to guarantee bold wins everywhere (including links)
    onload() {
      frappe.utils.add_style(`
        .datatable .fv-bold { font-weight: 700 !important; }
      `);
    },

    formatter(value, row, column, data, default_formatter) {
      let val = default_formatter(value, row, column, data);
      const isFormula = data && data.is_formula;

      // Make entire row bold if it's a formula
      if (isFormula) {
        val = `<strong>${val}</strong>`;
      }

      // Only add link for non-formula rows
      if (
        column.fieldname === "account" &&
        data &&
        data.account_name &&
        !isFormula
      ) {
        const label = frappe.utils.escape_html(data.account_name);
        val = `<a href="#" class="grey"
          onclick="frappe.query_reports['Profitability View'].open_general_ledger('${encodeURIComponent(
            data.account_name
          )}'); return false;">${label}</a>`;
      }

      return val;
    },

    open_general_ledger(section_label) {
      section_label = decodeURIComponent(section_label);

      const fiscal_year = frappe.query_report.get_filter_value("fiscal_year");
      const report_name = "Profitability View";

      frappe.call({
        method: "casino_navy.utils.get_accounts_for_section",
        args: {
          company: frappe.query_report.get_filter_value("company"),
          section_label,
          report_name,
        },
        freeze: true,
        freeze_message: __("Loading mapped accounts..."),

        callback(r) {
          if (!r.message) {
            frappe.msgprint(__("No accounts found."));
            return;
          }

          const accounts = r.message.accounts || [];
          const acc_company = r.message.company || null;

          if (!accounts.length) {
            frappe.msgprint(
              __("No mapped accounts found for section: {0}", [section_label])
            );
            return;
          }

          if (!acc_company) {
            frappe.msgprint(
              __("Unable to determine the company for these accounts.")
            );
            return;
          }

          // Fetch FY dates
          frappe.db
            .get_value("Fiscal Year", fiscal_year, [
              "year_start_date",
              "year_end_date",
            ])
            .then((res) => {
              const fy = res.message || {};

              frappe.route_options = {
                company: acc_company,        // 🔥 Use company returned from Python
                account: accounts,
                from_date: fy.year_start_date,
                to_date: fy.year_end_date,
              };

              frappe.set_route("query-report", "General Ledger");
            });
        },
      });
    },

    tree: false,
    name_field: "account",
    parent_field: "parent_account",
    initial_depth: 1,
  };
});