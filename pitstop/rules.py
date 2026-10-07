"""The banking module's Bank Transaction Rules as one more kind of pairing.

A rule says what a recurring line is when no document exists for it (bank fees, social charges, a
subscription); validating the pairing creates that document the way the /banking page does, so the
created voucher is flagged as such and an undo cancels it.

A label the user keeps booking on the same account is offered as a rule. The answer is kept the way the cash
flow forecast keeps its own proposals: a Bank Transaction Rule, Accepted or Rejected, whose
`detected_from_description` is the label's key, so neither ever offers that label again.
"""

import frappe
from erpnext.accounts.cash_flow_forecast.recurring_patterns import (
	ACCEPTED,
	PROPOSED,
	REJECTED,
	match_condition,
	normalise_description,
)
from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
	create_bulk_bank_entry_and_reconcile,
	create_bulk_payment_entry_and_reconcile,
)
from frappe import _
from frappe.utils import add_days, flt, getdate
from frappe.utils.caching import request_cache

from pitstop.ranking import LOOK_BACK_DAYS

# Booked on one same account this many times, a recurring label is worth a rule
MIN_BOOKINGS_FOR_A_RULE = 2
OFFER_LINE_FIELDS = ["name", "company", "date", "description", "credit", "deposit", "withdrawal"]


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


def rule_offers(bank_account: str, open_lines: list) -> list[dict]:
	"""Rules worth offering: labels of open lines the user booked on one same account at least twice before,
	that no rule covers and no rule was ever accepted or declined for.

	A rule the forecast merely proposed for the label does not count: the offer answers it.
	"""
	if not open_lines:
		return []
	since = add_days(min(getdate(line.date) for line in open_lines), -LOOK_BACK_DAYS)
	habits = booking_habits(bank_account, since)
	answered = set(
		frappe.get_all(
			"Bank Transaction Rule",
			filters={
				"company": open_lines[0].company,
				"detected_from_description": ("is", "set"),
				"proposal_status": ("in", [ACCEPTED, REJECTED]),
			},
			pluck="detected_from_description",
		)
	)
	lines_by_key = {}
	for line in open_lines:
		key = habit_key(line)
		if key in habits and key[0] not in answered and not matching_rule(line):
			lines_by_key.setdefault(key, []).append(line)
	return [
		{
			"key": key[0],
			"transaction_type": key[1],
			"account": habits[key].account,
			"booked": len(habits[key].lines),
			"lines": [line.name for line in lines],
			"condition": match_condition(key[0], habits[key].lines + lines),
		}
		for key, lines in lines_by_key.items()
	]


def habit_key(line) -> tuple[str, str]:
	"""The label stripped of dates, numbers and operation words, as the forecast's recurring series key it."""
	return normalise_description(line.description), "Deposit" if flt(line.credit) > 0 else "Withdrawal"


def booking_habits(bank_account: str, since) -> dict:
	"""Label key -> the account its past lines were all booked on by a bank entry, and those lines.

	One line of the key settled any other way, or booked elsewhere, and the key is no habit.
	"""
	lines = frappe.get_all(
		"Bank Transaction",
		filters={
			"bank_account": bank_account,
			"docstatus": 1,
			"allocated_amount": (">", 0),
			"date": (">=", since),
		},
		fields=OFFER_LINE_FIELDS,
	)
	booked_on = booking_accounts(bank_account, [line.name for line in lines])
	lines_by_key = {}
	for line in lines:
		key = habit_key(line)
		if key[0]:
			lines_by_key.setdefault(key, []).append(line)
	habits = {}
	for key, key_lines in lines_by_key.items():
		accounts = {booked_on.get(line.name) for line in key_lines}
		if len(key_lines) >= MIN_BOOKINGS_FOR_A_RULE and len(accounts) == 1 and None not in accounts:
			habits[key] = frappe._dict(account=accounts.pop(), lines=key_lines)
	return habits


def booking_accounts(bank_account: str, line_names: list[str]) -> dict[str, str]:
	"""Line -> the one account its bank entries booked it on, without a party; other lines are left out."""
	links = frappe.get_all(
		"Bank Transaction Payments",
		filters={"parenttype": "Bank Transaction", "parent": ("in", line_names or [""])},
		fields=["parent", "payment_document", "payment_entry"],
	)
	entries = [link.payment_entry for link in links if link.payment_document == "Journal Entry"]
	counterparts = {}
	for row in frappe.get_all(
		"Journal Entry Account",
		filters={
			"parent": ("in", entries or [""]),
			"account": ("!=", frappe.db.get_value("Bank Account", bank_account, "account")),
			"docstatus": 1,
		},
		fields=["parent", "account", "party"],
	):
		counterparts.setdefault(row.parent, set()).add(None if row.party else row.account)
	accounts_by_line = {}
	for link in links:
		accounts = counterparts.get(link.payment_entry) if link.payment_document == "Journal Entry" else None
		accounts_by_line.setdefault(link.parent, set()).update(accounts or {None})
	return {
		line: next(iter(accounts))
		for line, accounts in accounts_by_line.items()
		if len(accounts) == 1 and None not in accounts
	}


def answer_rule_offer(bank_account: str, key: str, transaction_type: str, status: str) -> str:
	"""Record the user's answer as a Bank Transaction Rule: Accepted, it books such lines on this page;
	Rejected, it never does, and neither is offered again.

	The forecast's own proposal for the label, if any, carries the answer, so the label keeps one rule.
	"""
	offer, company = find_offer(bank_account, key, transaction_type)
	proposed = frappe.db.get_value(
		"Bank Transaction Rule",
		{"company": company, "detected_from_description": key, "proposal_status": PROPOSED},
	)
	rule = (
		frappe.get_doc("Bank Transaction Rule", proposed)
		if proposed
		else frappe.new_doc("Bank Transaction Rule", rule_name=key.capitalize(), company=company)
	)
	rule.update(
		{
			"transaction_type": transaction_type,
			"classify_as": "Bank Entry",
			"bank_entry_type": "Single Account",
			# The account the user actually booked on, over the forecast's guess
			"account": offer["account"],
			"proposal_status": status,
			"detected_from_description": key,
			# Kept when declined too, as the forecast keeps its own: a condition is mandatory, and flipping
			# the status in the desk makes the rule work
			"description_rules": [offer["condition"]],
			"rule_description": _("Offered after {0} lines booked on {1}").format(
				offer["booked"], offer["account"]
			),
		}
	)
	rule.save()
	return rule.name


def find_offer(bank_account: str, key: str, transaction_type: str) -> tuple[dict, str]:
	"""The offer as computed now, not as the page last saw it, and the company it is for."""
	open_lines = frappe.get_list(
		"Bank Transaction",
		filters={"bank_account": bank_account, "docstatus": 1, "unallocated_amount": ("!=", 0)},
		fields=OFFER_LINE_FIELDS,
	)
	for offer in rule_offers(bank_account, open_lines):
		if (offer["key"], offer["transaction_type"]) == (key, transaction_type):
			return offer, open_lines[0].company
	frappe.throw(_("Dokos no longer offers a rule for {0}: reload the page").format(key))
