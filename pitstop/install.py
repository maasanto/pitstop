"""What Pitstop adds to a site on install and migrate. Kept apart from the page's modules, whose erpnext imports
vary by version: a migrate must never depend on them."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

AUTO_RECONCILIATION_SETTING = "automatically_reconcile_bank_transactions"

# On Accounts Settings next to erpnext's own hourly rule evaluation, so it moves into erpnext as one standard field
CUSTOM_FIELDS = {
	"Accounts Settings": [
		{
			"fieldname": AUTO_RECONCILIATION_SETTING,
			"fieldtype": "Check",
			"label": "Automatically reconcile bank transactions",
			"description": "If enabled, automatic reconciliation will run every hour on the unreconciled bank "
			"transactions of the last 90 days",
			"insert_after": "automatically_run_rules_on_unreconciled_transactions",
			"default": "0",
		}
	]
}


def create_custom_fields_for_pitstop() -> None:
	create_custom_fields(CUSTOM_FIELDS, update=True)
