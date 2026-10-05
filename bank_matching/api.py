import frappe
from frappe import _
from frappe.utils import flt, getdate

from bank_matching.pairing import LINE_FIELDS, as_matchable, build_pairing, reconcile, search_documents

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
	return {
		"pairings": [build_pairing(as_matchable(line)) for line in lines[:MAX_LINES]],
		"truncated": len(lines) > MAX_LINES,
	}


@frappe.whitelist()
def search(bank_transaction: str, query: str = "") -> list[dict]:
	return search_documents(get_line(bank_transaction, "read"), query, SEARCH_LIMIT)


@frappe.whitelist(methods=["POST"])
def reconcile_pairings(pairings: list[dict]) -> list[dict]:
	"""Reconcile each pairing on its own, so that one refused pairing leaves the others reconciled."""
	results = []
	for index, pairing in enumerate(pairings):
		savepoint = f"bank_matching_pairing_{index}"
		frappe.db.savepoint(savepoint)
		try:
			reconcile(get_line(pairing["bank_transaction"], "write"), pairing["documents"])
		except frappe.ValidationError as error:
			roll_back_pairing(savepoint)
			results.append({"bank_transaction": pairing["bank_transaction"], "error": str(error)})
			continue
		if not frappe.in_test:
			# A later refusal must not undo this pairing; the reconciliation commits its payments alike
			frappe.db.commit()  # nosemgrep
		results.append({"bank_transaction": pairing["bank_transaction"], "error": None})
	return results


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
