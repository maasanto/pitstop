import frappe
from erpnext.accounts.doctype.bank_transaction.bank_transaction import (
	PENDING_STATUS,
	unreconcile_transaction,
)
from frappe import _
from frappe.utils import add_months, cint, flt, get_first_day, getdate, nowdate

from pitstop.pairing import (
	LINE_FIELDS,
	PAYMENT_FILES,
	as_matchable,
	build_pairing,
	reconcile,
	search_documents,
)
from pitstop.ranking import AccountContext
from pitstop.refusals import get_refused, set_refused
from pitstop.rules import ACCEPTED, REJECTED, answer_rule_offer, apply_rule, rule_offers
from pitstop.rules import create_rule as create_bank_rule

PARTY_TYPES = ("Payable", "Receivable")

MAX_LINES = 300
# The page asks for its lines a page at a time, so the first ones show while the others are scored
PAGE_LENGTH = 25
# The picker lists every open document and filters them in the browser
# ponytail: one payload of up to 500 rows, page it server-side if a company keeps more open
SEARCH_LIMIT = 500
# An operation the bank feed only announces is not booked yet: nothing to reconcile, nothing to count
BOOKED_LINES = {"docstatus": 1, "status": ("!=", PENDING_STATUS)}


@frappe.whitelist()
def get_bank_accounts() -> list[dict]:
	return frappe.get_list(
		"Bank Account",
		filters={"is_company_account": 1, "disabled": 0},
		fields=["name", "account_name", "bank", "company", "account"],
		order_by="account_name",
	)


@frappe.whitelist()
def get_pairings(bank_account: str, from_date: str, to_date: str, start: int = 0) -> dict:
	"""The pairings of a page of the period's open lines, latest first; the first page also brings the rule
	offers, drawn from every line the page would show."""
	lines = get_lines(bank_account, from_date, to_date, {"unallocated_amount": ("!=", 0)})
	shown = lines[:MAX_LINES]
	page = [as_matchable(line) for line in shown[cint(start) : cint(start) + PAGE_LENGTH]]
	refused = get_refused([line.name for line in page])
	context = AccountContext(page) if page else None
	return {
		"pairings": [build_pairing(line, refused.get(line.name, []), context) for line in page],
		"total": len(shown),
		"truncated": len(lines) > MAX_LINES,
		"rule_offers": rule_offers(bank_account, shown) if not cint(start) else None,
	}


@frappe.whitelist(methods=["POST"])
def accept_rule_offer(bank_account: str, key: str, transaction_type: str) -> str:
	frappe.has_permission("Bank Account", "read", bank_account, throw=True)
	return answer_rule_offer(bank_account, key, transaction_type, ACCEPTED)


@frappe.whitelist(methods=["POST"])
def decline_rule_offer(bank_account: str, key: str, transaction_type: str) -> str:
	frappe.has_permission("Bank Account", "read", bank_account, throw=True)
	return answer_rule_offer(bank_account, key, transaction_type, REJECTED)


@frappe.whitelist(methods=["POST"])
def set_refused_proposals(bank_transaction: str, proposals: list[str]) -> None:
	get_line(bank_transaction, "write")
	set_refused(bank_transaction, proposals)


@frappe.whitelist()
def search(bank_transaction: str, query: str = "") -> list[dict]:
	return search_documents(get_line(bank_transaction, "read"), query, SEARCH_LIMIT)


@frappe.whitelist(methods=["POST"])
def reconcile_pairings(pairings: list[dict]) -> list[dict]:
	"""Reconcile each pairing on its own, so that one refused pairing leaves the others reconciled.

	Each result names the vouchers the reconciliation created, which an undo cancels.
	"""
	results = []
	for index, pairing in enumerate(pairings):
		name = pairing["bank_transaction"]
		savepoint = f"pitstop_pairing_{index}"
		frappe.db.savepoint(savepoint)
		try:
			line = get_line(name, "write")
			linked_before = linked_vouchers(name)
			if pairing.get("rule"):
				apply_rule(name, pairing["rule"])
			else:
				reconcile(line, pairing["documents"])
		except frappe.ValidationError as error:
			roll_back_pairing(savepoint)
			results.append({"bank_transaction": name, "error": str(error), "created": []})
			continue
		if not frappe.in_test:
			# A later refusal must not undo this pairing; the reconciliation commits its payments alike
			frappe.db.commit()  # nosemgrep
		chosen = {(document["doctype"], document["name"]) for document in pairing.get("documents") or []}
		is_file = any(doctype in PAYMENT_FILES for doctype, _name in chosen)
		# A file's payments belong to the file: an undo may unlink them, never cancel them
		created = set() if is_file else linked_vouchers(name) - linked_before - chosen
		results.append(
			{
				"bank_transaction": name,
				"error": None,
				"created": [{"doctype": doctype, "name": voucher} for doctype, voucher in sorted(created)],
				"undoable": not (is_file and cleared_file(name)),
			}
		)
	return results


@frappe.whitelist(methods=["POST"])
def undo_pairings(pairings: list[dict]) -> list[dict]:
	"""Put validated lines back as they were: unlinked, and the vouchers the validation created cancelled.

	Unlinking alone would leave those vouchers submitted, booking the money a second time once the line
	is reconciled again.
	"""
	results = []
	for index, pairing in enumerate(pairings):
		name = pairing["bank_transaction"]
		savepoint = f"pitstop_undo_{index}"
		frappe.db.savepoint(savepoint)
		try:
			undo_pairing(name, {(v["doctype"], v["name"]) for v in pairing.get("created") or []})
		except frappe.ValidationError as error:
			roll_back_pairing(savepoint)
			results.append({"bank_transaction": name, "error": str(error)})
			continue
		results.append({"bank_transaction": name, "error": None})
	return results


def undo_pairing(name: str, created: set) -> None:
	file = cleared_file(name)
	if file:
		frappe.throw(_("Bank Transaction {0} cleared {1}, which this page cannot undo").format(name, file))
	# Only vouchers still linked to this line: the request must not cancel any document it names
	to_cancel = created & linked_vouchers(name)
	unreconcile_transaction(name)
	for doctype, voucher in sorted(to_cancel):
		document = frappe.get_doc(doctype, voucher)
		if document.docstatus == 1:
			document.check_permission("cancel")
			document.cancel()


def cleared_file(bank_transaction: str) -> str | None:
	"""The Payment Order or direct debit file whose transit account the line cleared.

	Unlinking would leave the file marked as executed and its clearing entry booked.
	"""
	entries = [voucher for doctype, voucher in linked_vouchers(bank_transaction) if doctype == "Journal Entry"]
	if not entries:
		return None
	for doctype in PAYMENT_FILES:
		# Dokos v5 clears a Payment Order without booking a clearing entry: the line cleared no file
		if not frappe.get_meta(doctype).has_field("clearing_journal_entry"):
			continue
		file = frappe.db.get_value(doctype, {"clearing_journal_entry": ("in", entries)})
		if file:
			return file
	return None


def linked_vouchers(bank_transaction: str) -> set:
	return {
		(row.payment_document, row.payment_entry)
		for row in frappe.get_all(
			"Bank Transaction Payments",
			filters={"parenttype": "Bank Transaction", "parent": bank_transaction},
			fields=["payment_document", "payment_entry"],
		)
	}


@frappe.whitelist(methods=["POST"])
def create_rule(bank_transaction: str, rule_name: str, contains: str, account: str) -> str:
	return create_bank_rule(get_line(bank_transaction, "read"), rule_name, contains, account)


@frappe.whitelist()
def get_bookable_accounts(bank_transaction: str) -> list[dict]:
	"""The accounts a recurring line can be booked on: every posting account of the line's company."""
	line = get_line(bank_transaction, "read")
	return frappe.get_list(
		"Account",
		filters={"company": line.company, "is_group": 0, "disabled": 0, "account_type": ("not in", PARTY_TYPES)},
		fields=["name", "account_name", "root_type"],
		order_by="root_type, account_name",
	)


@frappe.whitelist()
def get_progress(bank_account: str, months: int = 12) -> list[dict]:
	"""Lines and reconciled lines per month, latest first: the page's progress and its streak."""
	frappe.has_permission("Bank Account", "read", bank_account, throw=True)
	rows = frappe.get_list(
		"Bank Transaction",
		filters={
			"bank_account": bank_account,
			**BOOKED_LINES,
			"date": (">=", add_months(get_first_day(nowdate()), -(cint(months) - 1))),
		},
		fields=["date", "unallocated_amount"],
		limit_page_length=0,
	)
	by_month = {}
	for row in rows:
		month = by_month.setdefault(str(row.date)[:7], {"month": str(row.date)[:7], "lines": 0, "reconciled": 0})
		month["lines"] += 1
		if not flt(row.unallocated_amount):
			month["reconciled"] += 1
	return sorted(by_month.values(), key=lambda month: month["month"], reverse=True)


@frappe.whitelist()
def get_period_totals(bank_account: str, from_date: str, to_date: str) -> dict:
	"""Money in and money out over the period, each with the amount already reconciled."""
	lines = get_lines(bank_account, from_date, to_date, {})
	totals = {direction: {"total": 0.0, "reconciled": 0.0, "lines": 0} for direction in ("in", "out")}
	for line in lines:
		direction = totals["in" if flt(line.credit) else "out"]
		direction["total"] += flt(line.credit) or flt(line.debit)
		direction["reconciled"] += flt(line.allocated_amount)
		direction["lines"] += 1
	return {**totals, "currency": lines[0].currency if lines else None}


def roll_back_pairing(savepoint: str) -> None:
	try:
		frappe.db.rollback(save_point=savepoint)
	except Exception:
		# The reconciliation commits once it creates a payment, which releases the savepoint: what
		# remains after that commit is the payment alone, as on the classic page
		frappe.db.rollback()


@frappe.whitelist()
def get_reconciled_lines(bank_account: str, from_date: str, to_date: str) -> list[dict]:
	lines = get_lines(bank_account, from_date, to_date, {"allocated_amount": (">", 0)})
	links = frappe.get_all(
		"Bank Transaction Payments",
		filters={"parenttype": "Bank Transaction", "parent": ("in", [line.name for line in lines] or [""])},
		fields=[
			"parent",
			"payment_document",
			"payment_entry",
			"allocated_amount",
			"party",
			"reconciliation_type",
		],
		order_by="idx",
	)
	created_by_reconciliation = payments_created_by_reconciliation(lines, links)
	documents_by_line = {}
	for link in links:
		link.created_by_reconciliation = (link.payment_entry in created_by_reconciliation) or (
			link.reconciliation_type == "Voucher Created"
		)
		documents_by_line.setdefault(link.parent, []).append(link)
	return [
		{
			"line": dict(line, amount=flt(line.credit) - flt(line.debit)),
			"documents": documents_by_line.get(line.name, []),
		}
		for line in lines
	]


def payments_created_by_reconciliation(lines, links) -> set[str]:
	"""Payment Entries the reconciliation of an invoice created: dated and referenced after their line."""
	line_by_name = {line.name: line for line in lines}
	payments = frappe.get_all(
		"Payment Entry",
		filters={
			"name": (
				"in",
				[link.payment_entry for link in links if link.payment_document == "Payment Entry"] or [""],
			)
		},
		fields=["name", "reference_no", "posting_date"],
	)
	payment_by_name = {payment.name: payment for payment in payments}
	created = set()
	for link in links:
		payment, line = payment_by_name.get(link.payment_entry), line_by_name[link.parent]
		if (
			payment
			and payment.reference_no in (line.reference_number, line.name)
			and payment.posting_date == line.date
		):
			created.add(payment.name)
	return created


def get_lines(bank_account: str, from_date: str, to_date: str, filters: dict) -> list:
	frappe.has_permission("Bank Account", "read", bank_account, throw=True)
	return frappe.get_list(
		"Bank Transaction",
		filters={
			"bank_account": bank_account,
			**BOOKED_LINES,
			"date": ("between", [getdate(from_date), getdate(to_date)]),
			**filters,
		},
		fields=LINE_FIELDS,
		order_by="date desc, name desc",
	)


def get_line(name: str, permission: str):
	line = frappe.get_doc("Bank Transaction", name)
	line.check_permission(permission)
	if line.docstatus != 1:
		frappe.throw(_("Bank Transaction {0} is not submitted").format(name))
	if line.status == PENDING_STATUS:
		frappe.throw(
			_("Bank Transaction {0} is only announced by the bank: reconcile it once the bank books it").format(
				name
			)
		)
	return as_matchable(frappe._dict({field: line.get(field) for field in LINE_FIELDS}))
