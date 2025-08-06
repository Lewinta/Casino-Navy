import frappe
import erpnext
from frappe.utils import flt
from frappe import msgprint
from  erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry as ERPNextJournalEntry

class JournalEntry(ERPNextJournalEntry):
	def on_update(self):
		self.set_bank_accounts()

	def set_bank_accounts(self):
		# This function will set the bank account for the journal entry accounts
		# that are missing it. It will use the account and company to find the bank account
		# and set it to the journal entry account

		BA = frappe.qb.DocType("Bank Account")
		JA = frappe.qb.DocType("Journal Entry Account")

		frappe.qb.update(JA).join(BA).on(
			(JA.account == BA.account)&
			(BA.is_company_account == 1)
		).set(
			JA.bank_account, BA.name
		).where(
			JA.parent == self.name
		).run()

	@frappe.whitelist()
	def get_balance(self, difference_account=None):
		if not self.get("accounts"):
			msgprint(_("'Entries' cannot be empty"), raise_exception=True)
		else:
			self.total_debit, self.total_credit = 0, 0
			diff = flt(self.difference, self.precision("difference"))

			# If any row without amount, set the diff on that row
			if diff:
				blank_row = None
				for d in self.get("accounts"):
					if not d.credit_in_account_currency and not d.debit_in_account_currency and diff != 0:
						blank_row = d

				if not blank_row:
					currencies = [a.account_currency for a in self.accounts if a.account_currency]
					if not difference_account and len(currencies) > 1:
						difference_account = frappe.get_value(
							"Company",
							self.company,
							"exchange_gain_loss_account"
						)
							
					blank_row = self.append(
						"accounts",
						{
							"account": difference_account,
							"cost_center": erpnext.get_default_cost_center(self.company),
						},
					)

				blank_row.exchange_rate = 1
				if diff > 0:
					blank_row.credit_in_account_currency = diff
					blank_row.credit = diff
				elif diff < 0:
					blank_row.debit_in_account_currency = abs(diff)
					blank_row.debit = abs(diff)

			self.set_total_debit_credit()
			self.validate_total_debit_and_credit()

			
@frappe.whitelist()
def get_reference_entry(doctype, name):
	"""
		Get the reference journal entry of a document

		:param doctype: The document type
		:param name: The document name
		:return: The name of the reference journal entry
	"""

	filters = {
		"reference_type": doctype,
		"reference_name": name
	}
	if name := frappe.db.exists("Journal Entry", filters):
		return name

	return None

