import frappe
from frappe import qb
from frappe.utils import today
from functools import lru_cache
from frappe.query_builder import Criterion
from erpnext.accounts.utils import get_balance_on
from frappe.utils.nestedset import get_descendants_of
from erpnext.setup.utils import get_exchange_rate as get_conversion_rate
from casino_navy.casino_navy.doctype.accountant_mapper.accountant_mapper import (
    _load_sections_from_mapper,
    _resolve_sections_leafs,
)

def get_exchange_rate(from_currency, to_currency, date=None, conversion_type="for_selling"):
    if from_currency == to_currency:
        return 1
    if not date:
        date = frappe.utils.today()
    if not frappe.db.exists("Currency", from_currency):
        frappe.throw(f"Currency {from_currency} not found")
    if not frappe.db.exists("Currency", to_currency):
        frappe.throw(f"Currency {to_currency} not found")
    exchange = get_conversion_rate(from_currency, to_currency, date, conversion_type)
    return exchange


@frappe.whitelist()
def get_bank_account(company, mop=None, account=None):
    if not mop and not account:
        frappe.throw("Please provide either a Mode of Payment or an Account")

    BA = qb.DocType('Bank Account')
    MP = qb.DocType('Mode of Payment')
    MA = qb.DocType('Mode of Payment Account')

    data = None

    if account:
        data = frappe.qb.from_(BA).where(
            (BA.account == account)&
            (BA.is_company_account == 1)
        ).select(
            BA.name
        ).limit(1).run(as_dict=True)

    elif mop:
        data = frappe.qb.from_(MP).join(MA).on(
            MP.name == MA.parent
        ).join(BA).on(
            MA.default_account == BA.account
        ).where(
            (MP.name == mop)&
            (BA.is_company_account == 1)&
            (MA.company == company)
        ).select(
            BA.name
        ).limit(1).run(as_dict=True)

    return data[0].name if data else None


@lru_cache(maxsize=None)
def _get_account_meta(account_name: str):
    if not account_name:
        return {"account_name": "", "parent_account": "", "account_type": ""}
    row = frappe.db.get_value(
        "Account", account_name, ["account_name", "parent_account", "account_type"], as_dict=True
    ) or {}
    return {
        "account_name": (row.get("account_name") or "").strip() or account_name,
        "parent_account": row.get("parent_account") or "",
        "account_type": row.get("account_type") or "",
    }

def _make_row_payload(
    account: str,              # real Account name or "" for non-clickable
    display_label: str,        # text shown in Account column
    periods, values: list[float],
    currency: str,
    year_start, year_end,
    parent_account: str = "",
    account_type: str = "",
    bold: int = 0,
):
    row = {
        "account": account,                     # clickable if non-empty
        "account_name": display_label,
        "parent_account": parent_account,
        "account_type": account_type,
        "year_start_date": year_start,
        "year_end_date": year_end,
        "from_date": year_start,
        "to_date": year_end,
        "currency": currency,
    }
    total = 0.0
    for i, p in enumerate(periods):
        v = float(values[i] if i < len(values) else 0)
        row[p["key"]] = v
        total += v
    row["total"] = total
    if bold:
        row["bold"] = 1
    return row

def move_luqapay_balance():
    # This function is intended to move 
    # All deposites from Luqapay mode of payments
    # to the main bank account
    A = qb.DocType('Account')
    parent_account = '13500 - LuqaPay/Jeton - X2'
    target_account = '13506 - Luqapay - X2'
    company = 'X2 - JMS Investment Group N.V'
    valid_accounts = get_descendants_of('Account', parent_account)
    conditions = [
        A.company == company,
        A.is_group == 0,
        A.name.isin(valid_accounts),
        A.name != target_account
    ]

    accounts = frappe.qb.from_(A).select(A.name).where(
        Criterion.all(conditions)
    ).run(as_dict=True)

    jv = frappe.new_doc('Journal Entry')
    jv.update({
        'company': company,
        'voucher_type': 'Bank Entry',
        'posting_date': today(),
        "multi_currency": 1,
        "cheque_no": "Luqapay Auto Balance Transfer",
        "cheque_date": today(),
    })
    acum_balance = base_acum_balance = .00
    for row in accounts:
        account = row.name
        balance = get_balance_on(account, today(), company=company, in_account_currency=True)
        base_balance = get_balance_on(account, today(), company=company, in_account_currency=False)
        acum_balance += balance
        base_acum_balance += base_balance
        if balance and base_balance > 0:
            jv.append('accounts', {
                'account': account,
                'credit_in_account_currency': balance,
                'credit': base_balance,
                'cost_center': frappe.get_value('Company', company, 'cost_center'),
            })
        
        if balance and base_balance < 0:
            jv.append('accounts', {
                'account': target_account,
                'debit_in_account_currency': abs(balance),
                'debit': abs(base_balance),
                'cost_center': frappe.get_value('Company', company, 'cost_center'),
            })
    if base_acum_balance > 0:
        jv.append('accounts', {
            'account': target_account,
            'debit_in_account_currency': acum_balance,
            'debit': base_acum_balance,
            'cost_center': frappe.get_value('Company', company, 'cost_center'),
        })
    elif base_acum_balance < 0:
        jv.append('accounts', {
            'account': target_account,
            'credit_in_account_currency': abs(acum_balance),
            'credit': abs(base_acum_balance),
            'cost_center': frappe.get_value('Company', company, 'cost_center'),
        })
    
    try:
        jv.save()
        return jv.submit()
    except Exception as e:
        content = f"Journal Entry: {jv.as_json()}\n\n{str(e)}\n\n{frappe.get_traceback()}"
        frappe.log_error("Luqapay Balance Transfer", content)
        

@frappe.whitelist()
def get_accounts_for_section(company: str, section_label: str, report_name: str = "Net Profit Line Summary"):
    sections = _load_sections_from_mapper(report_name, company)
    resolved = _resolve_sections_leafs(company, sections)

    if section_label not in resolved:
        frappe.throw(f"Section '{section_label}' not found in Accountant Mapper for {company}.")

    leafs = list(resolved[section_label].get("leafs") or [])

    if not leafs:
        return {
            "accounts": [],
            "company": None,
        }

    first_acc = leafs[0]
    acc_company = frappe.db.get_value("Account", first_acc, "company")

    return {
        "accounts": leafs,
        "company": acc_company,
    }