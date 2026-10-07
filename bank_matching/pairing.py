"""Pairings between bank lines and documents, from the app's scorer.

This module turns the scorer's suggestions into what the page shows: one proposal per document type, a
settlement of several receipts, and a confidence level drawn from the scorer's own thresholds.
"""

import frappe
from erpnext.accounts.doctype.bank_transaction.bank_reconciliation import (
	get_matching_payment_order,
	reconcile_from_payment_order,
)
from erpnext.accounts.doctype.sepa_direct_debit.services.settlement import (
	get_matching_direct_debit,
	reconcile_from_direct_debit,
)
from erpnext.accounts.page.bank_reconciliation.bank_reconciliation import BankReconciliation
from erpnext.accounts.page.bank_reconciliation.bank_transaction_match import BankTransactionMatch
from erpnext.accounts.page.bank_reconciliation.multi_party_reconciliation import (
	PROPOSE,
	get_reconciliation_mode,
	reconcile_multi_party_proposal,
)
from frappe import _
from frappe.utils import flt, getdate

from bank_matching.match_scoring import PRESELECT_THRESHOLD, Receipt, settlement_batches
from bank_matching.ranking import EXTRA_NUMBER_FIELD, SuggestionRanking, proposal_key
from bank_matching.rules import matching_rule, rule_proposal

LEVELS = ("high", "medium", "low")
# Beyond five leads the user searches rather than refuses one by one
MAX_PROPOSALS = 5
# Invoices are paid by a Payment Entry the reconciliation creates; the others already moved the money
INVOICE_TYPES = ("Sales Invoice", "Purchase Invoice", "Expense Claim")
# Transfers or direct debits the bank books as one movement for the whole file:
# (the one file of exactly the line's amount, how the line clears it, the file's date)
PAYMENT_FILES = {
	"Payment Order": (get_matching_payment_order, reconcile_from_payment_order, "posting_date"),
	"Sepa Direct Debit": (get_matching_direct_debit, reconcile_from_direct_debit, "collection_date"),
}
LINE_FIELDS = [
	"name",
	"company",
	"date",
	"description",
	"reference_number",
	"bank_party_name",
	"bank_party_iban",
	"bank_party_account_number",
	"bank_account",
	"currency",
	"credit",
	"debit",
	# What Bank Transaction Rules compare
	"deposit",
	"withdrawal",
	"unallocated_amount",
	"allocated_amount",
]


def as_matchable(line):
	"""The line in the shape the scorer and the reconciliation expect: its open amount, signed."""
	sign = 1 if flt(line.credit) > 0 else -1
	return frappe._dict(
		line,
		date=str(line.date),
		amount=sign * abs(flt(line.unallocated_amount)),
		unallocated_amount=abs(flt(line.unallocated_amount)),
	)


def build_pairing(line, refused: list[str]) -> dict:
	"""Every way Dokos sees to reconcile the line, the one it would pick first among those not refused."""
	ranking = SuggestionRanking(BankTransactionMatch([line], None))
	suggestions = ranking.rank(set(refused))
	proposals = file_proposals(line)
	proposals += [document_proposal(suggestion) for suggestion in shortlist(suggestions)]
	proposals += settlement_proposals(line, ranking.candidates)
	rule = matching_rule(line)
	if rule:
		# A document already booked for the amount wins: applying the rule would book the line twice
		proposals.append(rule_proposal(rule, "low" if any(map(is_exact_amount, proposals)) else "high"))
	# Stable sort: within a level, a released file, the scorer's own order, then the rule
	proposals.sort(key=lambda proposal: LEVELS.index(proposal["level"]))
	return {"line": describe_line(line), "proposals": proposals, "refused": refused}


def file_proposals(line) -> list[dict]:
	"""The released Payment Order paid by a withdrawal, or the direct debit file collected by a deposit.

	erpnext only names a file whose total is exactly the line's amount and the only one to be.
	"""
	doctype = "Payment Order" if line.amount < 0 else "Sepa Direct Debit"
	find_file, _clear, date_field = PAYMENT_FILES[doctype]
	name = find_file(line.name)
	if not name:
		return []
	reasons = [{"signal": "amount", "exact": True, "description": _("Same amount")}]
	if name.lower() in (line.description or "").lower():
		reasons.append({"signal": "reference", "exact": True, "description": _("Number in the label")})
	file = frappe._dict(
		doctype=doctype,
		name=name,
		signed_amount=line.amount,
		grand_total=abs(line.amount),
		posting_date=frappe.db.get_value(doctype, name, date_field),
		match_reasons=reasons,
	)
	return [
		{
			"key": proposal_key(file),
			"level": "high",
			"score": None,
			"documents": [describe_document(file)],
			"creates_payment": False,
		}
	]


def reconcile_file(line, doctype: str, names: list[str]) -> None:
	find_file, clear, _date_field = PAYMENT_FILES[doctype]
	if names != [find_file(line.name)]:
		frappe.throw(
			_("{0} {1} no longer matches this line exactly: reload the page").format(_(doctype), ", ".join(names))
		)
	clear(line.name, names[0])


def is_exact_amount(proposal) -> bool:
	if proposal.get("settlement"):
		return not proposal["settlement"]["fee"]
	return any(
		reason["signal"] == "amount" and reason["exact"]
		for document in proposal["documents"]
		for reason in document["reasons"]
	)


def shortlist(suggestions):
	"""The runners-up the user falls back on when refusing a lead, plus the best of each type: a strong
	payment must not hide behind stronger invoices of another party, nor the reverse."""
	seen_types = set()
	for rank, suggestion in enumerate(suggestions):
		if rank < MAX_PROPOSALS or suggestion.doctype not in seen_types:
			seen_types.add(suggestion.doctype)
			yield suggestion


def document_proposal(suggestion) -> dict:
	if suggestion.vgtSelected:
		# The scorer's preselection rule, backtested at 91% precision
		level = "high"
	elif suggestion.match_score >= PRESELECT_THRESHOLD:
		level = "medium"
	else:
		level = "low"
	return {
		"key": proposal_key(suggestion),
		"level": level,
		"score": suggestion.match_score,
		"documents": [describe_document(suggestion)],
		"creates_payment": creates_payment(suggestion),
	}


def creates_payment(document) -> bool:
	return document.doctype in INVOICE_TYPES and not (document.get("is_pos") or document.get("is_paid"))


def settlement_proposals(line, candidates) -> list[dict]:
	payments = {c.name: c for c in candidates or [] if c.doctype == "Payment Entry"}
	receipts = [
		Receipt(name, payment.signed_amount, getdate(payment.posting_date), payment.mode_of_payment)
		for name, payment in payments.items()
	]
	settlements = settlement_batches(line.amount, getdate(line.date), receipts)
	if not settlements:
		return []
	best = settlements[0]
	documents = [payments[name] for name in best.keys]
	is_certain = len(settlements) == 1 and not best.fee
	return [
		{
			"key": "settlement:" + ",".join(best.keys),
			"level": "medium" if is_certain else "low",
			"score": None,
			"documents": [describe_document(document) for document in documents],
			"creates_payment": False,
			"settlement": {
				"total": best.total,
				"fee": best.fee,
				"other_groupings": len(settlements) - 1,
				"reasons": describe_settlement(best, documents),
			},
		}
	]


def describe_settlement(settlement, documents) -> list[dict]:
	modes = {document.mode_of_payment for document in documents}
	dates = sorted(getdate(document.posting_date) for document in documents)
	same_batch = len(modes) == 1 and (dates[-1] - dates[0]).days <= 2
	return [
		{
			"signal": "amount",
			"exact": not settlement.fee,
			"description": _("Total of the payments") if not settlement.fee else _("Total less card fees"),
		},
		{
			"signal": "batch",
			"exact": same_batch,
			"description": _("Same days, same mode of payment") if same_batch else _("Consecutive payments"),
		},
	]


def describe_line(line) -> dict:
	return {
		"name": line.name,
		"date": line.date,
		"description": line.description,
		"reference_number": line.reference_number,
		"bank_party_name": line.bank_party_name,
		"amount": line.amount,
		"currency": line.currency,
	}


def describe_document(document) -> dict:
	return {
		"doctype": document.doctype,
		"name": document.name,
		"party_type": document.party_type,
		"party": document.party,
		"party_name": document.party_name,
		"amount": abs(flt(document.signed_amount)),
		"grand_total": flt(document.grand_total),
		"posting_date": document.posting_date,
		"due_date": document.get("due_date"),
		"reference": document_reference(document),
		"mode_of_payment": document.get("mode_of_payment"),
		"score": document.get("match_score"),
		"reasons": document.get("match_reasons") or [],
	}


def document_reference(document) -> str | None:
	if document.doctype == "Journal Entry":
		# erpnext gives a journal entry as "name: cheque number", or its remark when it has none
		return (document.get("reference_string") or "").partition(": ")[2] or None
	return document.get(EXTRA_NUMBER_FIELD.get(document.doctype, "")) or None


def search_documents(line, query: str, limit: int) -> list[dict]:
	"""Open documents of every type matching the query, the scorer's favourites first."""
	ranking = SuggestionRanking(BankTransactionMatch([line], None))
	ranking.rank()
	query = (query or "").strip().lower()
	matches = [
		candidate
		for candidate in ranking.candidates
		if not query
		or any(
			query in str(value or "").lower()
			for value in (
				candidate.name,
				candidate.party,
				candidate.party_name,
				candidate.get(EXTRA_NUMBER_FIELD.get(candidate.doctype, "")),
				f"{abs(flt(candidate.signed_amount)):.2f}",
			)
		)
	]
	matches.sort(key=lambda candidate: -flt(candidate.get("match_score")))
	return [document_proposal(candidate) for candidate in matches[:limit]]


def reconcile(line, documents: list[dict]) -> None:
	"""Reconcile the line with documents of one type, re-read from the database rather than trusted."""
	doctypes = {document["doctype"] for document in documents}
	if len(doctypes) != 1:
		frappe.throw(_("A bank line is reconciled with documents of a single type, got {0}").format(doctypes))
	doctype = doctypes.pop()
	names = [document["name"] for document in documents]
	if doctype in PAYMENT_FILES:
		reconcile_file(line, doctype, names)
		return
	rows = {
		row["name"]: dict(row, doctype=doctype)
		for row in BankTransactionMatch([line], doctype, match=False).get_linked_documents(
			document_names=names
		)
	}
	missing = [name for name in names if name not in rows]
	if missing:
		frappe.throw(
			_("{0} is no longer open for reconciliation: reload the page").format(", ".join(missing))
		)
	selected = [rows[name] for name in names]
	if get_reconciliation_mode(selected) == PROPOSE:
		# Invoices of several parties: one payment each, the oldest due first
		reconcile_multi_party_proposal(line.name, documents)
	else:
		BankReconciliation([line], selected).reconcile()
