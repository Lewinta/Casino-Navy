// Copyright (c) 2025, Lewin Villar and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Chart of Accounts Comparison"] = {
	"filters": [
		{
			fieldname: "main_company",
			label: __("Main Company"),
			fieldtype: "Link",
			options: "Company",
			reqd:1,
			get_query: function() {
				return {
					filters: {
						is_group: 1
					}
				};
			}

		},
		// mismatches_only
		{
			fieldname: "compaies",
			label: __("Companies"),
			fieldtype: "MultiSelectList",
			get_data: function(txt) {
				return frappe.db.get_link_options("Company", txt, {
					name:  ["!=", frappe.query_report.get_filter_value("main_company")]
					
				});
			},
		},
		{
			fieldname: "mismatches_only",
			label: __("Show Mismatches Only"),
			fieldtype: "Check",
			default: 1,
			description: __("Show only accounts that have mismatches between the companies.")
		},
	],
	formatter: function (value, row, columnDef, dataContext, default_formatter) {
		value = default_formatter(value, row, columnDef, dataContext);
		if (columnDef.id.startsWith("status") && value) {
			let color = "";
			switch (value) {
				case "Match":
					color = "green";
					break;
				case "Different Name":
					color = "orange";
					break;
				case "Not in Parent":
					color = "red";
					break;
				case "Doesn't exists":
					color = "grey";
					break;
			}
			value = `<span style="font-size: 10px; margin-left:-5px;" class="indicator-pill ${color}">
						<span style="font-size: 10px; ${color == "red" ? "color:red" : ""}"><b>${value}</b></span>
					</span>`;
		}
		return value;
	}
};
