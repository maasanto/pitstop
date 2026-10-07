"""Dokos's automatic reconciliation, run every hour instead of on a click.

The setting is a check on Accounts Settings (see install.py). The job runs what the classic page's "Automatic
reconciliation" button runs.
"""

import frappe
from erpnext.accounts.page.bank_reconciliation.auto_bank_reconciliation import auto_bank_reconciliation
from frappe.utils import add_days, flt, nowdate

from pitstop.api import roll_back_pairing
from pitstop.install import AUTO_RECONCILIATION_SETTING as SETTING

# The job reads every open line of this window each hour: older lines rarely find a new document, and the
# page opens on the same 90 days
LOOK_BACK_DAYS = 90


@frappe.whitelist()
def get_auto_reconciliation() -> dict:
	return {
		"enabled": bool(frappe.db.get_single_value("Accounts Settings", SETTING)),
		"can_change": frappe.has_permission("Accounts Settings", "write"),
	}


@frappe.whitelist(methods=["POST"])
def set_auto_reconciliation(enabled: bool) -> None:
	settings = frappe.get_doc("Accounts Settings")
	settings.check_permission("write")
	settings.set(SETTING, int(enabled))
	settings.save()


def scheduled_reconciliation() -> None:
	if frappe.db.get_single_value("Accounts Settings", SETTING):
		reconcile_open_lines()


def reconcile_open_lines() -> None:
	"""Each line on its own: a line that fails is logged and the others stay reconciled."""
	for index, line in enumerate(open_lines()):
		savepoint = f"pitstop_auto_reconciliation_{index}"
		frappe.db.savepoint(savepoint)
		try:
			# As JSON, the way the button posts its rows: the classic page parses their dates from strings
			auto_bank_reconciliation(frappe.as_json([line]))
		except Exception:
			roll_back_pairing(savepoint)
			frappe.log_error(
				title="Automatic bank reconciliation failed",
				reference_doctype="Bank Transaction",
				reference_name=line.name,
			)
			continue
		if not frappe.in_test:
			frappe.db.commit()  # nosemgrep


def open_lines() -> list[dict]:
	"""The rows the classic page hands its button: whole lines, with the signed amount it reads."""
	lines = frappe.get_all(
		"Bank Transaction",
		filters={
			"docstatus": 1,
			"status": "Unreconciled",
			"unallocated_amount": ("!=", 0),
			"date": (">=", add_days(nowdate(), -LOOK_BACK_DAYS)),
		},
		fields=["*"],
		order_by="date asc, name asc",
	)
	for line in lines:
		line.amount = flt(line.credit) - flt(line.debit)
	return lines
