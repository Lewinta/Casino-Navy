# Copyright (c) 2024, Lewin Villar and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt
from frappe.model.document import Document
from casino_navy.utils import get_exchange_rate

class TransactionLedger(Document):
	def validate(self):
		self.fetch_accounts()
		self.validate_bank_account()
		self.validate_types()	

	def on_submit(self):
		self.make_entry()
	
	def on_cancel(self):
		self.cancel_entry()
	
	def on_trash(self):
		self.delete_entry()
	
	def make_entry(self):
		jv = frappe.new_doc("Journal Entry")
		jv.update({
			"company": self.company,
			"voucher_type": "Bank Entry",
			"posting_date": self.date,
			"cheque_no": f"Transaction Ledeger {self.name}",
			"reference_type": self.doctype,
			"reference_name": self.name,
			"cheque_date": self.date,
			"multi_currency": 1,
		})

		company = frappe.get_doc("Company", self.company)
		
		default_cost_center = company.cost_center
		default_currency = company.default_currency
		bank_details = self.get_bank_account_details()
		bank_exchange_rate = get_exchange_rate(
			bank_details.account_currency,
			default_currency,
			self.date,
		)
		
		charge_exchange_rate = get_exchange_rate(
			self.charge_currency,
			default_currency,
			self.date,
		)

		# Amount
		if self.transaction_type == "Deposit":
			amount = abs(flt(self.amount, 6)) 
			base_amount = amount * bank_exchange_rate
			fee_amount = abs(flt(self.fee, 6))
			base_fee_amount = .00
			
			row = jv.append("accounts", {
				"account": bank_details.bank_account,
				"account_currency": bank_details.account_currency,
				"exchange_rate": bank_exchange_rate,
				"debit_in_account_currency": amount,
				"debit": base_amount,				
				"bank_account": self.bank,
				"cost_center": default_cost_center,
			})
			
			if self.fee:
	
				fee_exchange_rate = get_exchange_rate(
					self.fee_currency,
					default_currency,
					self.date,
				)
				base_fee_amount = flt(fee_amount) * flt(fee_exchange_rate)
				row = jv.append("accounts", {
					"account": self.fee_account,
					"account_currency": self.fee_currency,
					"exchange_rate": fee_exchange_rate,
					"debit_in_account_currency": fee_amount,
					"debit": base_fee_amount,
					"cost_center": default_cost_center,
				})

			row = jv.append("accounts", {
				"account": self.charge_account,
				"account_currency": self.charge_currency,
				"exchange_rate": charge_exchange_rate,
				"credit_in_account_currency": (amount + fee_amount),
				"credit": base_amount + base_fee_amount,
				"cost_center": default_cost_center,
			})	
		elif self.transaction_type == "Withdraw":
			amount = abs(flt(self.amount, 6)) 
			base_amount = amount * bank_exchange_rate
			fee_amount = abs(flt(self.fee, 6))
			base_fee_amount = .00
			
			row = jv.append("accounts", {
				"account": bank_details.bank_account,
				"account_currency": bank_details.account_currency,
				"exchange_rate": bank_exchange_rate,
				"credit_in_account_currency": amount,
				"credit": base_amount,				
				"bank_account": self.bank,
				"cost_center": default_cost_center,
			})

			if self.fee:
				fee_exchange_rate = get_exchange_rate(
					self.fee_currency,
					default_currency,
					self.date,
				)
				base_fee_amount = fee_amount * fee_exchange_rate
				row = jv.append("accounts", {
					"account": self.fee_account,
					"account_currency": self.fee_currency,
					"exchange_rate": fee_exchange_rate,
					"credit_in_account_currency": fee_amount,
					"credit": base_fee_amount,
					"cost_center": default_cost_center,
				})

			row = jv.append("accounts", {
				"account": self.charge_account,
				"account_currency": self.charge_currency,
				"exchange_rate": charge_exchange_rate,
				"debit_in_account_currency": (amount + fee_amount),
				"debit": base_amount + base_fee_amount,
				"cost_center": default_cost_center,
			})
			
		try: 
			jv.save()
			jv.submit()
			return jv.name
		except Exception as e:
			content = f"Journal Entry: {jv.as_json()}\n\n{str(e)}\n\n{frappe.get_traceback()}"
			frappe.log_error("Transaction Ledger", content)   

	def cancel_entry(self):
		filters = {
			"reference_type": self.doctype,
			"reference_name": self.name,
			"docstatus": 1
		}
		if name:= frappe.db.exists("Journal Entry", filters):
			jv = frappe.get_doc("Journal Entry", name)
			jv.cancel()
	
	def delete_entry(self):
		filters = {
			"reference_type": self.doctype,
			"reference_name": self.name,
			"docstatus": ["in", [0, 2]]
		}
		if name:= frappe.db.exists("Journal Entry", filters):
			jv = frappe.get_doc("Journal Entry", name)
			jv.delete()
		
	@frappe.whitelist()
	def fetch_accounts(self):
		bank_details = self.get_bank_account_details()
		self.bank_account = bank_details.bank_account
		self.bank_currency = bank_details.account_currency
		self.get_charge_details("charge")
		self.get_charge_details("fee")
		print(f"""
			bank_account: {self.bank_account}\n
			bank_currency: {self.bank_currency}\n
			charge_account: {self.charge_account}\n
			charge_currency: {self.charge_currency}\n
			fee_account: {self.fee_account}\n
			fee_currency: {self.fee_currency}
		""")

	def get_bank_account_details(self):
		BA = frappe.qb.DocType("Bank Account")
		A = frappe.qb.DocType("Account")
		result = frappe.qb.from_(BA).join(A).on(
			BA.account == A.name
		).select(
			A.name.as_("bank_account"),
			A.account_currency
		).where(
			(BA.name == self.bank)
		).run(as_dict=True)
		
		if not result:
			frappe.throw(f"Bank Account '{self.bank}' does not have an account")
		
		return result[0]

	def validate_bank_account(self):
		bank_account_company = frappe.get_value("Bank Account", self.bank, "company")
		if bank_account_company != self.company:
			frappe.throw(f"Bank Account '{self.bank}' does not belong to Company '{self.company}'")
		
		# let's make sure the fee and the bank account currency are the same
		if self.fee and self.fee > 0:
			bank_details = self.get_bank_account_details()
			bank_currency = bank_details.account_currency
			account_currency = frappe.get_value("Account", self.fee_account, "account_currency")
			if account_currency != bank_currency:
				frappe.throw(f"Fee currency '{account_currency}' does not match bank account currency '{bank_currency}'")
		
	def validate_types(self):
		if not self.charge_type:
			return

		charge  = frappe.get_doc("Charge Type", self.charge_type)
		if self.transaction_type == "Deposit" and charge.type != "Income":
			frappe.throw(f"Charge Type '{self.charge_type}' is not an income type")
		elif self.transaction_type == "Withdraw" and charge.type != "Expense":
			frappe.throw(f"Charge Type '{self.charge_type}' is not an expense type")
		
		if self.fee_type:
			fee_type = frappe.get_value("Charge Type", self.fee_type, "type")
			if fee_type != "Fee":
				frappe.throw(f"Charge Type '{self.fee_type}' is not a fee type")
			
	def get_charge_details(self, charge_type):
		MOPA = frappe.qb.DocType("Mode of Payment Account")
		CT = frappe.qb.DocType("Charge Type")
		A = frappe.qb.DocType("Account")

		charge = ''
		
		if charge_type == "charge":
			charge = self.charge_type
		if  charge_type == "fee":
			charge = self.fee_type
		
		if not charge:
			return

		result  = frappe.qb.from_(MOPA).join(CT).on(
			MOPA.parent == CT.name
		).join(A).on(
			MOPA.default_account == A.name
		).select(
			MOPA.default_account,
			A.account_currency
		).where(
			(MOPA.company == self.company)&
			(CT.name == charge)
		).run(as_dict=True)

		if not result:
			frappe.throw(f"Charge Type '{charge}' does not have a default account")
		
		if charge_type == "charge":
			self.charge_account = result[0].default_account
			self.charge_currency = result[0].account_currency
		
		if charge_type == "fee":
			self.fee_account = result[0].default_account
			self.fee_currency = result[0].account_currency
