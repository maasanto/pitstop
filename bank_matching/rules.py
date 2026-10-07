"""The banking module's Bank Transaction Rules as one more kind of pairing.

A rule says what a recurring line is when no document exists for it (bank fees, social charges, a
subscription); validating the pairing creates that document the way the /banking page does, so the
created voucher is flagged as such and an undo cancels it.
"""

import frappe
from erpnext.accounts.cash_flow_forecast.recurring_patterns import ACCEPTED
from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
	create_bulk_bank_entry_and_reconcile,
	create_bulk_payment_entry_and_reconcile,
)
from frappe import _
from frappe.utils import flt
from frappe.utils.caching import request_cache


@request_cache
def company_rules(company: str) -> list:
	# The forecast's weekly job proposes rules on a guessed account, and its declined ones keep their
	# conditions: only rules a user wrote or accepted book lines
	names = frappe.get_all(
		"Bank Transaction Rule",
		filters={"company": company, "proposal_status": ("in", ["", ACCEPTED])},
		order_by="priority asc",
		pluck="name",
	)
	return [frappe.get_doc("Bank Transaction Rule", name) for name in names]


def matching_rule(line):
	"""The first rule matching the line, by priority as in the banking module, if this page can apply it."""
	rule = next((rule for rule in company_rules(line.company) if rule.evaluate_rule(line)), None)
	return rule if rule and is_applicable(rule) else None


def is_applicable(rule) -> bool:
	# Several accounts take amount formulas only /banking evaluates; a transfer needs the other bank's line
	if rule.classify_as == "Payment Entry":
		return True
	return rule.classify_as == "Bank Entry" and rule.bank_entry_type != "Multiple Accounts"


def rule_proposal(rule, level: str) -> dict:
	return {
		"key": f"rule:{rule.name}",
		"level": level,
		"score": None,
		"documents": [],
		"creates_payment": False,
		"rule": {
			"name": rule.name,
			"rule_name": rule.rule_name,
			"classify_as": rule.classify_as,
			"account": rule.account,
			"party_type": rule.party_type,
			"party": rule.party,
		},
	}


def apply_rule(line_name: str, rule_name: str) -> None:
	line = frappe.get_doc("Bank Transaction", line_name)
	rule = frappe.get_doc("Bank Transaction Rule", rule_name)
	rule.check_permission("read")
	if not (is_applicable(rule) and rule.evaluate_rule(line)):
		frappe.throw(
			_("Rule {0} no longer applies to {1}: reload the page").format(rule.rule_name, line_name)
		)
	if rule.classify_as == "Payment Entry":
		create_bulk_payment_entry_and_reconcile([line_name], rule.party_type, rule.party, rule.account)
	else:
		create_bulk_bank_entry_and_reconcile([line_name], rule.account)


def create_rule(line, rule_name: str, contains: str, account: str) -> str:
	"""A rule booking every line whose label contains `contains`, in the line's direction, on `account`."""
	if not (contains or "").strip():
		frappe.throw(_("Give the part of the label that identifies these lines"))
	rule = frappe.get_doc(
		{
			"doctype": "Bank Transaction Rule",
			"rule_name": rule_name,
			"company": line.company,
			"transaction_type": "Deposit" if flt(line.credit) > 0 else "Withdrawal",
			"classify_as": "Bank Entry",
			"bank_entry_type": "Single Account",
			"account": account,
			"description_rules": [{"check": "Contains", "value": contains.strip()}],
		}
	).insert()
	return rule.name
