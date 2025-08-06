import frappe
from frappe.utils import today
from datetime import datetime
from frappe.exceptions import ValidationError
from erpnext.accounts.utils import get_balance_on
from erpnext.setup.utils import get_exchange_rate
import json

def parse_date(date_str):
    try:
        if date_str:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        return today()
    except ValueError:
        raise ValidationError("Invalid date format. Please provide a valid date (YYYY-MM-DD).")

@frappe.whitelist()
def get_balance(company, bank, date=None, cost_center=None, in_account_currency=True):
    """
    Fetches the balance of a specific bank account for a given company and date.
    """
    if not company or not bank:
        raise ValidationError("Both 'company' and 'bank' parameters are required.")

    try:
        date = parse_date(date)
        
        if not frappe.db.exists("Company", company):
            raise frappe.DoesNotExistError(f"Company '{company}' does not exist.")
        if not frappe.db.exists("Bank Account", bank):
            raise frappe.DoesNotExistError(f"Bank Account '{bank}' does not exist.")
        
        company_doc = frappe.get_doc("Company", company)
        company_currency = company_doc.default_currency
        bank_data = get_bank_account_details(bank)

        exchange_rate = 1
        if company_currency != bank_data.account_currency:
            exchange_rate = get_exchange_rate(
                bank_data.account_currency,
                company_currency,
                date,
                "for_selling"
            )

        balance = get_balance_on(
            account=bank_data.bank_account,
            date=date,
            company=company_doc.name,
            in_account_currency=in_account_currency,
            cost_center=cost_center,
            ignore_account_permission=True
        )
        return balance

    except Exception as e:
        frappe.log_error(title="Error in get_balance API", message=f"{str(e)}\n{frappe.get_traceback()}")
        raise

@frappe.whitelist()
def add_transaction(data):
    """
    Add a new transaction to the Transaction Ledger.
    """
    try:
        try:
            transaction_data = frappe.parse_json(data)
        except Exception:
            raise ValidationError("Invalid JSON provided in data.")

        required_fields = ["company", "transaction_type", "bank", "date", "amount", "charge_type"]
        missing_fields = [field for field in required_fields if not transaction_data.get(field)]
        
        if missing_fields:
            frappe.throw(f"Missing required fields: {', '.join(missing_fields)}")

        if transaction_data.get("fee") and not transaction_data.get("fee_type"):
            frappe.throw("Field 'fee_type' is required when 'fee' is provided.")

        date = parse_date(transaction_data.get("date"))

        transaction = frappe.get_doc({
            "doctype": "Transaction Ledger",
            "company": transaction_data.get("company"),
            "transaction_type": transaction_data.get("transaction_type"),
            "bank": transaction_data.get("bank"),
            "date": date,
            "amount": transaction_data.get("amount"),
            "fee": transaction_data.get("fee"),
            "fee_type": transaction_data.get("fee_type"),
            "charge_type": transaction_data.get("charge_type"),
            "exchange_rate": transaction_data.get("exchange_rate") or 1.0,
            "transaction_id": transaction_data.get("transaction_id"),
            "third_party_reference": transaction_data.get("third_party_reference"),
            "username": transaction_data.get("username"),
            "description": transaction_data.get("description")
        })

        transaction.save()
        transaction.submit()

        return {"status": "success", "message": "Transaction added successfully", "transaction": transaction.as_dict()}

    except Exception as e:
        frappe.log_error(title="Error in add_transaction API", message=f"{str(e)}\n{frappe.get_traceback()}")
        return {"status": "error", "message": str(e)}

def get_bank_account_details(bank):
    BA = frappe.qb.DocType("Bank Account")
    A = frappe.qb.DocType("Account")
    result = (
        frappe.qb.from_(BA)
        .join(A).on(BA.account == A.name)
        .select(A.name.as_("bank_account"), A.account_currency)
        .where(BA.name == bank)
        .run(as_dict=True)
    )

    if not result:
        frappe.throw(f"Bank Account '{bank}' does not have an associated Account.")

    return result[0]
