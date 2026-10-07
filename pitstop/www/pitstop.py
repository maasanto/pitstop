import frappe
from frappe import _
from frappe.translate import get_translation_version

no_cache = 1


def get_context():
	if frappe.session.user == "Guest" or not frappe.has_permission("Bank Transaction", "read"):
		frappe.throw(_("You need read access to Bank Transactions to reconcile them"), frappe.PermissionError)

	return frappe._dict(
		boot={
			"csrf_token": frappe.sessions.get_csrf_token(),
			"lang": frappe.local.lang,
			"translations_version": get_translation_version(),
			"user": frappe.session.user,
			"default_currency": frappe.db.get_default("currency"),
			"date_format": frappe.db.get_default("date_format"),
		}
	)
