"""The banking module's Bank Transaction Rules as one more kind of pairing.

A rule says what a recurring line is when no document exists for it (bank fees, social charges, a
subscription); validating the pairing creates that document the way the /banking page does, so the
created voucher is flagged as such and an undo cancels it.

A label the user keeps booking on the same account, or as payments of the same party, is offered as a rule. The answer is kept the way the cash
flow forecast keeps its own proposals: a Bank Transaction Rule, Accepted or Rejected, whose
`detected_from_description` is the label's key, so neither ever offers that label again.
"""

from collections import namedtuple

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

# Booked the same way this many times, a recurring label is worth a rule
MIN_BOOKINGS_FOR_A_RULE = 2
OFFER_LINE_FIELDS = ["name", "company", "date", "description", "credit", "deposit", "withdrawal"]
# How a past line was booked, in the terms of the rule that would book the next one: a bank entry on an account
# (no party), or a payment of a party on the party's own account
Booking = namedtuple("Booking", ["classify_as", "account", "party_type", "party"])


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
			"account_label": account_label(rule.account) if rule.account else None,
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
	"""Rules worth offering: labels of open lines the user booked the same way at least twice before, on one
	account or as payments of one party, that no rule covers and no rule was ever accepted or declined for.

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
			**habits[key].booking._asdict(),
			"account_label": account_label(habits[key].booking.account),
			"party_name": party_name(habits[key].booking),
			"booked": len(habits[key].lines),
			"lines": [line.name for line in lines],
			"condition": match_condition(key[0], habits[key].lines + lines),
		}
		for key, lines in lines_by_key.items()
	]


def account_label(account: str) -> str:
	"""`6061 - Water` rather than `Water - ACME`: the number users know, without the company suffix."""
	number, name = frappe.get_cached_value("Account", account, ["account_number", "account_name"])
	return f"{number} - {name}" if number else name


def party_name(booking: Booking) -> str | None:
	if not booking.party:
		return None
	title_field = frappe.get_meta(booking.party_type).get_title_field()
	return frappe.db.get_value(booking.party_type, booking.party, title_field) or booking.party


def habit_key(line) -> tuple[str, str]:
	"""The label stripped of dates, numbers and operation words, as the forecast's recurring series key it."""
	return normalise_description(line.description), "Deposit" if flt(line.credit) > 0 else "Withdrawal"


def booking_habits(bank_account: str, since) -> dict:
	"""Label key -> how its past lines were all booked, and those lines: on one account by a bank entry, or by
	payments of one party.

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
	booked_as = line_bookings(bank_account, [line.name for line in lines])
	lines_by_key = {}
	for line in lines:
		key = habit_key(line)
		if key[0]:
			lines_by_key.setdefault(key, []).append(line)
	habits = {}
	for key, key_lines in lines_by_key.items():
		bookings = {booked_as.get(line.name) for line in key_lines}
		if len(key_lines) >= MIN_BOOKINGS_FOR_A_RULE and len(bookings) == 1 and None not in bookings:
			habits[key] = frappe._dict(booking=bookings.pop(), lines=key_lines)
	return habits


def line_bookings(bank_account: str, line_names: list[str]) -> dict[str, Booking]:
	"""Line -> how it was booked, when all its vouchers booked it the same way; other lines are left out."""
	links = frappe.get_all(
		"Bank Transaction Payments",
		filters={"parenttype": "Bank Transaction", "parent": ("in", line_names or [""])},
		fields=["parent", "payment_document", "payment_entry"],
	)
	vouchers = {doctype: [] for doctype in ("Journal Entry", "Payment Entry")}
	for link in links:
		vouchers.get(link.payment_document, []).append(link.payment_entry)
	bookings = {
		**bank_entry_bookings(bank_account, vouchers["Journal Entry"]),
		**party_payment_bookings(vouchers["Payment Entry"]),
	}
	bookings_by_line = {}
	for link in links:
		bookings_by_line.setdefault(link.parent, set()).add(
			bookings.get((link.payment_document, link.payment_entry))
		)
	return {
		line: next(iter(found))
		for line, found in bookings_by_line.items()
		if len(found) == 1 and None not in found
	}


def bank_entry_bookings(bank_account: str, entries: list[str]) -> dict[tuple, Booking]:
	"""Journal entries booking the bank line on one other account, without a party."""
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
	return {
		("Journal Entry", entry): Booking("Bank Entry", next(iter(accounts)), None, None)
		for entry, accounts in counterparts.items()
		if len(accounts) == 1 and None not in accounts
	}


def party_payment_bookings(payments: list[str]) -> dict[tuple, Booking]:
	"""Payments of a party allocated to no document, with the party's own account: what a payment rule makes.

	A line that paid invoices needs no rule: the scorer already knows its party and finds the next invoice, where
	a rule would only add an unallocated payment.
	"""
	return {
		("Payment Entry", payment.name): Booking(
			"Payment Entry",
			payment.paid_to if payment.payment_type == "Pay" else payment.paid_from,
			payment.party_type,
			payment.party,
		)
		for payment in frappe.get_all(
			"Payment Entry",
			filters={
				"name": ("in", payments or [""]),
				"docstatus": 1,
				"party": ("is", "set"),
				"total_allocated_amount": 0,
			},
			fields=["name", "payment_type", "party_type", "party", "paid_from", "paid_to"],
		)
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
			"classify_as": offer["classify_as"],
			"bank_entry_type": "Single Account",
			# The account the user actually booked on, over the forecast's guess
			"account": offer["account"],
			"party_type": offer["party_type"],
			"party": offer["party"],
			"proposal_status": status,
			"detected_from_description": key,
			# Kept when declined too, as the forecast keeps its own: a condition is mandatory, and flipping
			# the status in the desk makes the rule work
			"description_rules": [offer["condition"]],
			"rule_description": _("Offered after {0} payments of {1}").format(offer["booked"], offer["party_name"])
			if offer["party"]
			else _("Offered after {0} lines booked on {1}").format(offer["booked"], offer["account_label"]),
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
