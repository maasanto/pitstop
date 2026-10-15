import frappe
from frappe import _
from frappe.translate import get_translation_version

no_cache = 1


def has_app_permission(app_info=None) -> bool:
	return frappe.session.user != "Guest" and frappe.has_permission("Bank Transaction", "read")


def get_context():
	if not has_app_permission():
		frappe.throw(_("You need read access to Bank Transactions to reconcile them"), frappe.PermissionError)

	return frappe._dict(
		boot={
			"csrf_token": frappe.sessions.get_csrf_token(),
			"lang": frappe.local.lang,
			"translations_version": get_translation_version(),
			"user": frappe.session.user,
			"default_currency": frappe.db.get_default("currency"),
			"date_format": frappe.db.get_default("date_format"),
			"desk_theme": frappe.db.get_value("User", frappe.session.user, "desk_theme"),
		}
	)
