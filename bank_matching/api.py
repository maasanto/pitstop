import frappe
from erpnext.accounts.doctype.bank_transaction.bank_transaction import unreconcile_transaction
from frappe import _
from frappe.utils import add_months, cint, flt, get_first_day, getdate, nowdate

from bank_matching.pairing import LINE_FIELDS, as_matchable, build_pairing, reconcile, search_documents
from bank_matching.refusals import get_refused, set_refused
from bank_matching.rules import ACCEPTED, REJECTED, answer_rule_offer, apply_rule, rule_offers
from bank_matching.rules import create_rule as create_bank_rule

PARTY_TYPES = ("Payable", "Receivable")

# ponytail: every open line of the period is scored on each load, about 10 ms a line on a small site;
# score per page or cache per line if large accounts feel it.
MAX_LINES = 200
SEARCH_LIMIT = 20


@frappe.whitelist()
def get_bank_accounts() -> list[dict]:
	return frappe.get_list(
		"Bank Account",
		filters={"is_company_account": 1, "disabled": 0},
		fields=["name", "account_name", "bank", "company", "account"],
		order_by="account_name",
	)


@frappe.whitelist()
def get_pairings(bank_account: str, from_date: str, to_date: str) -> dict:
	lines = get_lines(bank_account, from_date, to_date, {"unallocated_amount": ("!=", 0)})
	refused = get_refused([line.name for line in lines[:MAX_LINES]])
	return {
		"pairings": [
			build_pairing(as_matchable(line), refused.get(line.name, [])) for line in lines[:MAX_LINES]
		],
		"truncated": len(lines) > MAX_LINES,
		"rule_offers": rule_offers(bank_account, lines[:MAX_LINES]),
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
		savepoint = f"bank_matching_pairing_{index}"
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
		created = linked_vouchers(name) - linked_before - chosen
		results.append(
			{
				"bank_transaction": name,
				"error": None,
				"created": [{"doctype": doctype, "name": voucher} for doctype, voucher in sorted(created)],
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
		savepoint = f"bank_matching_undo_{index}"
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
	# Only vouchers still linked to this line: the request must not cancel any document it names
	to_cancel = created & linked_vouchers(name)
	unreconcile_transaction(name)
	for doctype, voucher in sorted(to_cancel):
		document = frappe.get_doc(doctype, voucher)
		if document.docstatus == 1:
			document.check_permission("cancel")
			document.cancel()


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
			"docstatus": 1,
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
			"docstatus": 1,
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
	return as_matchable(frappe._dict({field: line.get(field) for field in LINE_FIELDS}))
