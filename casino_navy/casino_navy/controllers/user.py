import frappe
import json
from frappe import clear_cache

@frappe.whitelist()
def impersonate(user):
	if frappe.session.user == "Administrator":
		clear_cache()
		frappe.local.login_manager.login_as(user)
		return str(user)
	else:
		return False
