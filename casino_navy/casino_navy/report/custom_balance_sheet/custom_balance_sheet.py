# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.accounts.report.financial_statements import (
    get_columns,
    get_data,
    get_filtered_list_for_consolidated_report,
    get_period_list,
)


def execute(filters=None):
    period_list = get_period_list(
        filters.from_fiscal_year,
        filters.to_fiscal_year,
        filters.period_start_date,
        filters.period_end_date,
        filters.filter_based_on,
        filters.periodicity,
        company=filters.company,
    )

    filters.period_start_date = period_list[0]["year_start_date"]

    currency = filters.presentation_currency or frappe.get_cached_value(
        "Company", filters.company, "default_currency"
    )

    asset = get_data(
        filters.company,
        "Asset",
        "Debit",
        period_list,
        only_current_fiscal_year=False,
        filters=filters,
        accumulated_values=filters.accumulated_values,
    )

    liability = get_data(
        filters.company,
        "Liability",
        "Credit",
        period_list,
        only_current_fiscal_year=False,
        filters=filters,
        accumulated_values=filters.accumulated_values,
    )

    equity = get_data(
        filters.company,
        "Equity",
        "Credit",
        period_list,
        only_current_fiscal_year=False,
        filters=filters,
        accumulated_values=filters.accumulated_values,
    )

    # Build provisional P/L and total (credit) like core
    provisional_profit_loss, total_credit = get_provisional_profit_loss(
        asset, liability, equity, period_list, filters.company, currency
    )

    message, opening_balance = check_opening_balance(asset, liability, equity)

    # If previous year is not closed, core logic adjusts provisional P/L by opening balance
    if opening_balance and round(opening_balance, 2) != 0:
        # Prepare "Unclosed Fiscal Years Profit / Loss (Credit)" row
        unclosed = {
            "account_name": "'" + _("Unclosed Fiscal Years Profit / Loss (Credit)") + "'",
            "account": "'" + _("Unclosed Fiscal Years Profit / Loss (Credit)") + "'",
            "warn_if_negative": True,
            "currency": currency,
        }
        for period in period_list:
            unclosed[period.key] = opening_balance
            if provisional_profit_loss:
                provisional_profit_loss[period.key] = provisional_profit_loss[period.key] - opening_balance
        unclosed["total"] = opening_balance
    else:
        unclosed = None

    def build_assets_minus_liabilities_row():
        """Assets - Liabilities = Total Asset (Debit) - Total Liability (Credit)"""
        if not (asset and liability):
            return None
        a_tot = asset[-2]  
        l_tot = liability[-2]
        row = {
            "account_name": "Assets - Liabilities",
            "account": "Assets - Liabilities",
            "currency": currency,
        }
        total_sum = 0.0
        for p in period_list:
            v = flt(a_tot.get(p.key)) - flt(l_tot.get(p.key))
            row[p.key] = v
            total_sum += flt(v)
        
        row["total"] = total_sum
        return row

    def build_total_equity_row():
        """Total Equity = Total Equity (Credit) + Provisional Profit / Loss (Credit)"""
        if not (equity and provisional_profit_loss):
            return None
        e_tot = equity[-2]
        row = {
            "account_name": "Total Equity",
            "account": "Total Equity",
            "currency": currency,
        }
        total_sum = 0.0
        for p in period_list:
            v = flt(e_tot.get(p.key)) + flt(provisional_profit_loss.get(p.key))
            row[p.key] = v
            total_sum += flt(v)
        row["total"] = total_sum
        return row

    assets_minus_liabilities = build_assets_minus_liabilities_row()
    total_equity_after_pl = build_total_equity_row()

    
    data = []
    data.extend(asset or [])
    data.extend(liability or [])

    if assets_minus_liabilities:
        data.append(assets_minus_liabilities)

    data.extend(equity or [])

    if unclosed:
        data.append(unclosed)

    if provisional_profit_loss:
        data.append(provisional_profit_loss)

    if total_equity_after_pl:
        data.append(total_equity_after_pl)

    if total_credit:
        data.append(total_credit)

    columns = get_columns(
        filters.periodicity, period_list, filters.accumulated_values, company=filters.company
    )

    chart = get_chart_data(filters, columns, asset, liability, equity)

    report_summary = get_report_summary(
        period_list, asset, liability, equity, provisional_profit_loss, currency, filters
    )

    return columns, data, message, chart, report_summary


def get_provisional_profit_loss(
    asset, liability, equity, period_list, company, currency=None, consolidated=False
):
    provisional_profit_loss = {}
    total_row = {}
    if asset and (liability or equity):
        total = total_row_total = 0
        currency = currency or frappe.get_cached_value("Company", company, "default_currency")
        total_row = {
            "account_name": "'" + _("Total (Credit)") + "'",
            "account": "'" + _("Total (Credit)") + "'",
            "warn_if_negative": True,
            "currency": currency,
        }
        has_value = False

        for period in period_list:
            key = period if consolidated else period.key
            effective_liability = 0.0
            if liability:
                effective_liability += flt(liability[-2].get(key))
            if equity:
                effective_liability += flt(equity[-2].get(key))

            provisional_profit_loss[key] = flt(asset[-2].get(key)) - effective_liability
            total_row[key] = effective_liability + provisional_profit_loss[key]

            if provisional_profit_loss[key]:
                has_value = True

            total += flt(provisional_profit_loss[key])
            provisional_profit_loss["total"] = total

            total_row_total += flt(total_row[key])
            total_row["total"] = total_row_total

        if has_value:
            provisional_profit_loss.update(
                {
                    "account_name": "'" + _("Provisional Profit / Loss (Credit)") + "'",
                    "account": "'" + _("Provisional Profit / Loss (Credit)") + "'",
                    "warn_if_negative": True,
                    "currency": currency,
                }
            )

    return provisional_profit_loss, total_row


def check_opening_balance(asset, liability, equity):
    # Check if previous year balance sheet closed
    opening_balance = 0
    float_precision = cint(frappe.db.get_default("float_precision")) or 2
    if asset:
        opening_balance = flt(asset[-1].get("opening_balance", 0), float_precision)
    if liability:
        opening_balance -= flt(liability[-1].get("opening_balance", 0), float_precision)
    if equity:
        opening_balance -= flt(equity[-1].get("opening_balance", 0), float_precision)

    opening_balance = flt(opening_balance, float_precision)
    if opening_balance:
        return _("Previous Financial Year is not closed"), opening_balance
    return None, None


def get_report_summary(
    period_list,
    asset,
    liability,
    equity,
    provisional_profit_loss,
    currency,
    filters,
    consolidated=False,
):

    net_asset, net_liability, net_equity, net_provisional_profit_loss = 0.0, 0.0, 0.0, 0.0

    if filters.get("accumulated_values"):
        period_list = [period_list[-1]]

    # from consolidated financial statement
    if filters.get("accumulated_in_group_company"):
        period_list = get_filtered_list_for_consolidated_report(filters, period_list)

    for period in period_list:
        key = period if consolidated else period.key
        if asset:
            net_asset += asset[-2].get(key)
        if liability:
            net_liability += liability[-2].get(key)
        if equity:
            net_equity += equity[-2].get(key)
        if provisional_profit_loss:
            net_provisional_profit_loss += provisional_profit_loss.get(key)

    return [
        {"value": net_asset, "label": _("Total Asset"), "datatype": "Currency", "currency": currency},
        {
            "value": net_liability,
            "label": _("Total Liability"),
            "datatype": "Currency",
            "currency": currency,
        },
        {"value": net_equity, "label": _("Total Equity"), "datatype": "Currency", "currency": currency},
        {
            "value": net_provisional_profit_loss,
            "label": _("Provisional Profit / Loss (Credit)"),
            "indicator": "Green" if net_provisional_profit_loss > 0 else "Red",
            "datatype": "Currency",
            "currency": currency,
        },
    ]


def get_chart_data(filters, columns, asset, liability, equity):
    labels = [d.get("label") for d in columns[2:]]

    asset_data, liability_data, equity_data = [], [], []

    for p in columns[2:]:
        if asset:
            asset_data.append(asset[-2].get(p.get("fieldname")))
        if liability:
            liability_data.append(liability[-2].get(p.get("fieldname")))
        if equity:
            equity_data.append(equity[-2].get(p.get("fieldname")))

    datasets = []
    if asset_data:
        datasets.append({"name": _("Assets"), "values": asset_data})
    if liability_data:
        datasets.append({"name": _("Liabilities"), "values": liability_data})
    if equity_data:
        datasets.append({"name": _("Equity"), "values": equity_data})

    chart = {"data": {"labels": labels, "datasets": datasets}}

    if not filters.accumulated_values:
        chart["type"] = "bar"
    else:
        chart["type"] = "line"

    return chart