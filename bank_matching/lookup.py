"""The other way round: from an open document, the bank lines it may have been paid by.

Each line is scored as the page scores it, so a document reads the same level here as on the line's card.
"""

import frappe
from erpnext.accounts.page.bank_reconciliation.bank_transaction_match import (
	PARTY_FIELD,
	PARTY_NAME_FIELD,
	PARTY_TYPES,
	BankTransactionMatch,
)
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from bank_matching.api import BOOKED_LINES, get_line
from bank_matching.pairing import (
	LINE_FIELDS,
	as_matchable,
	describe_document,
	describe_line,
	document_proposal,
	reconcile,
)
from bank_matching.ranking import LOOK_BACK_DAYS, SuggestionRanking

DOCUMENT_TYPES = ("Sales Invoice", "Purchase Invoice", "Payment Entry")
# ponytail: each scored line costs about 10 ms, so 60 lines keep the dialog under a second; a document
# whose line sits beyond the 60 closest amounts is not found, score in a background job if that bites.
MAX_SCORED_LINES = 60
MAX_LINES = 10
SEARCH_LIMIT = 5
# (doctype, what keeps it open to a bank line, its party name field, its amount field)
OPEN_DOCUMENTS = (
	("Sales Invoice", {"outstanding_amount": ("!=", 0)}, "customer_name", "grand_total"),
	("Purchase Invoice", {"outstanding_amount": ("!=", 0)}, "supplier_name", "grand_total"),
	("Payment Entry", {"clearance_date": ("is", "not set")}, "party_name", "paid_amount"),
)


@frappe.whitelist()
def get_lines_for_document(doctype: str, name: str) -> dict:
	document = get_open_document(doctype, name)
	frappe.has_permission("Bank Transaction", "read", throw=True)
	amount = open_amount(document)
	matches = []
	for line in map(as_matchable, closest_lines(document, amount)):
		candidate = score_document(line, document)
		if candidate and flt(candidate.get("match_score")) > 0:
			matches.append((line, candidate))
	# Stable sort: equal scores keep the closest amount first
	matches.sort(key=lambda match: -match[1].match_score)
	return {
		"document": describe_document(as_candidate(document, amount)),
		"lines": [
			{
				"line": describe_line(line),
				"bank_account": line.bank_account,
				"proposal": document_proposal(candidate),
			}
			for line, candidate in matches[:MAX_LINES]
		],
	}


@frappe.whitelist()
def search_open_documents(query: str) -> list[dict]:
	"""Open invoices and unreconciled payments whose number, party or amount matches the query."""
	query = (query or "").strip()
	if len(query) < 2:
		return []
	results = []
	for doctype, open_filters, party_field, amount_field in OPEN_DOCUMENTS:
		or_filters = [["name", "like", f"%{query}%"], [party_field, "like", f"%{query}%"]]
		if is_amount(query):
			or_filters.append([amount_field, "=", flt(query.replace(",", "."))])
		rows = frappe.get_list(
			doctype,
			filters={"docstatus": 1, **open_filters},
			or_filters=or_filters,
			fields=["name", "posting_date", f"{party_field} as party_name", f"{amount_field} as amount"],
			order_by="posting_date desc",
			limit_page_length=SEARCH_LIMIT,
		)
		results += [dict(row, doctype=doctype) for row in rows]
	return results


def is_amount(query: str) -> bool:
	try:
		float(query.replace(",", "."))
	except ValueError:
		return False
	return True


@frappe.whitelist(methods=["POST"])
def reconcile_document(doctype: str, name: str, bank_transaction: str) -> None:
	get_open_document(doctype, name)
	reconcile(get_line(bank_transaction, "write"), [{"doctype": doctype, "name": name}])


def get_open_document(doctype: str, name: str):
	if doctype not in DOCUMENT_TYPES:
		frappe.throw(
			_("Bank lines can be looked up for {0} only, not for {1}").format(
				", ".join(_(document_type) for document_type in DOCUMENT_TYPES), _(doctype)
			)
		)
	document = frappe.get_doc(doctype, name)
	document.check_permission("read")
	if document.docstatus != 1 or not open_amount(document):
		frappe.throw(_("{0} {1} has nothing left to reconcile with a bank line").format(_(doctype), name))
	return document


def open_amount(document) -> float:
	"""What a bank line still has to cover, by the scorer's own rule for each document type."""
	if document.doctype == "Payment Entry":
		return abs(flt(document.unreconciled_amount))
	if flt(document.unreconciled_amount) > 0:
		return flt(document.unreconciled_amount)
	return abs(flt(document.outstanding_amount))


def closest_lines(document, amount: float) -> list:
	"""The open lines nearest the document by amount, then by date, on the side its money moves."""
	lines = []
	for account, into_bank in money_sides(document):
		bank_accounts = company_bank_accounts(document.company, account)
		if not bank_accounts:
			continue
		filters = {
			"bank_account": ("in", bank_accounts),
			**BOOKED_LINES,
			"unallocated_amount": ("!=", 0),
			"date": (">=", add_days(today(), -LOOK_BACK_DAYS)),
			"credit" if into_bank else "debit": (">", 0),
		}
		if document.doctype != "Payment Entry":
			# The scorer only offers an invoice to lines in its own currency
			filters["currency"] = document.currency
		lines += frappe.get_list("Bank Transaction", filters=filters, fields=LINE_FIELDS)
	posting_date = getdate(document.posting_date)
	lines.sort(
		key=lambda line: (
			abs(abs(flt(line.unallocated_amount)) - amount),
			abs((getdate(line.date) - posting_date).days),
		)
	)
	return lines[:MAX_SCORED_LINES]


def money_sides(document) -> list[tuple[str | None, bool]]:
	"""(ledger account of the bank, or None for any, whether money comes into it) the document may show on."""
	if document.doctype == "Payment Entry":
		# An internal transfer leaves one bank and enters another; otherwise only one side is a bank
		return [(document.paid_to, True), (document.paid_from, False)]
	is_refund = flt(document.outstanding_amount) < 0
	return [(None, (document.doctype == "Sales Invoice") != is_refund)]


def company_bank_accounts(company: str, account: str | None) -> list[str]:
	filters = {"company": company, "is_company_account": 1, "disabled": 0}
	if account:
		filters["account"] = account
	return frappe.get_all("Bank Account", filters=filters, pluck="name")


def score_document(line, document):
	"""The document as the scorer sees it from this line, or None when it is no candidate there."""
	ranking = SuggestionRanking(BankTransactionMatch([line], None))
	ranking.rank()
	return next(
		(
			candidate
			for candidate in ranking.candidates
			if candidate.doctype == document.doctype and candidate.name == document.name
		),
		None,
	)


def as_candidate(document, amount: float):
	"""The document in the shape describe_document expects from a scorer candidate."""
	return frappe._dict(
		document.as_dict(),
		party_type=PARTY_TYPES.get(document.doctype, document.get("party_type")),
		party=document.get(PARTY_FIELD[document.doctype]),
		party_name=document.get(PARTY_NAME_FIELD[document.doctype]),
		signed_amount=amount,
		grand_total=document.get("rounded_total") or document.get("grand_total") or document.get("paid_amount"),
	)
