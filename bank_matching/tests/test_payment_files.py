import frappe
from erpnext.accounts.doctype.payment_order import test_payment_order_release as payment_orders
from erpnext.accounts.doctype.payment_order.test_payment_order import create_test_bank_transaction
from erpnext.accounts.doctype.sepa_direct_debit import test_sepa_direct_debit_collection as direct_debits
from frappe.utils import flt

from bank_matching.api import get_pairings, reconcile_pairings, undo_pairings


def best_proposal(line):
	pairings = get_pairings(line.bank_account, str(line.date), str(line.date))["pairings"]
	return next(pairing for pairing in pairings if pairing["line"]["name"] == line.name)["proposals"][0]


def validate(line, proposal):
	[result] = reconcile_pairings([{"bank_transaction": line.name, "documents": proposal["documents"]}])
	return result


def undo(line, result):
	[undone] = undo_pairings([{"bank_transaction": line.name, "created": result["created"]}])
	return undone


def released_order_and_its_line(case):
	order = case.make_order()
	order.release_to_bank()
	total = flt(sum(row.amount for row in order.references))
	return order, create_test_bank_transaction(case.bank_account, total)


class TestPaymentOrderProposals(payment_orders.PaymentOrderReleaseTestCase):
	def test_a_released_order_is_cleared_by_its_bank_line_and_stays_cleared(self):
		order, line = released_order_and_its_line(self)

		proposal = best_proposal(line)
		self.assertEqual((proposal["level"], proposal["documents"][0]["name"]), ("high", order.name))
		result = validate(line, proposal)

		self.assertIsNone(result["error"])
		self.assertFalse(result["undoable"])
		self.assertEqual(frappe.db.get_value("Payment Order", order.name, "status"), "Executed")
		self.assertIn("cannot undo", undo(line, result)["error"])
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "status"), "Reconciled")


class TestPaymentOrderWithoutTransitProposals(payment_orders.PaymentOrderReleaseTestCase):
	with_transit = False

	def test_undo_unlinks_the_payments_and_keeps_them_for_the_next_reconciliation(self):
		order, line = released_order_and_its_line(self)

		result = validate(line, best_proposal(line))
		self.assertTrue(result["undoable"])
		self.assertIsNone(undo(line, result)["error"])

		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "status"), "Unreconciled")
		payments = frappe.get_all("Payment Entry", filters={"payment_order": order.name}, pluck="docstatus")
		self.assertEqual(payments, [1, 1], "one payment per supplier, kept")
		self.assertIsNone(validate(line, best_proposal(line))["error"])
		self.assertEqual(frappe.db.count("Payment Entry", {"payment_order": order.name}), 2)
		self.assertEqual(frappe.db.get_value("Payment Order", order.name, "status"), "Executed")


class TestDirectDebitProposals(direct_debits.DirectDebitCollectionTestCase):
	def test_a_collected_file_is_cleared_by_its_bank_credit_and_stays_cleared(self):
		file = self.new_file([self.make_invoice(rate=40), self.make_invoice(rate=60)])
		file.insert()
		file.submit()
		line = self.make_bank_transaction(deposit=flt(file.total_amount))

		proposal = best_proposal(line)
		self.assertEqual((proposal["level"], proposal["documents"][0]["name"]), ("high", file.name))
		result = validate(line, proposal)

		self.assertIsNone(result["error"])
		self.assertFalse(result["undoable"])
		self.assertTrue(frappe.db.get_value("Sepa Direct Debit", file.name, "clearing_journal_entry"))
		self.assertIn("cannot undo", undo(line, result)["error"])
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "status"), "Reconciled")
