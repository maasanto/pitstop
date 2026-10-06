from datetime import date

import frappe
from erpnext.tests.utils import ERPNextTestSuite

from bank_matching.api import create_rule, get_pairings, reconcile_pairings, undo_pairings
from bank_matching.lookup import get_lines_for_document, reconcile_document

PAYMENT_DATE = date(2026, 9, 15)
COMPANY = "_Test Company"
ACCOUNTANT = "bank-matching-accountant@example.com"


class TestPairings(ERPNextTestSuite):
	def setUp(self):
		super().setUp()
		self.bank_account = self.get_bank_account()
		self.customer = self.get_customer("Acme Rentals", contact=("John", "Doe"))
		if not frappe.db.exists("User", ACCOUNTANT):
			frappe.get_doc(
				{"doctype": "User", "email": ACCOUNTANT, "first_name": "Accountant"}
			).insert().add_roles("Accounts User", "Accounts Manager")

	def get_bank_account(self):
		if not frappe.db.exists("Bank", "_Test Bank"):
			frappe.get_doc({"doctype": "Bank", "bank_name": "_Test Bank"}).insert()
		return (
			frappe.db.get_value("Bank Account", {"account": "_Test Bank - _TC", "bank": "_Test Bank"})
			or frappe.get_doc(
				{
					"doctype": "Bank Account",
					"account_name": "_Test Bank Account",
					"account": "_Test Bank - _TC",
					"company": COMPANY,
					"bank": "_Test Bank",
					"is_company_account": 1,
				}
			)
			.insert()
			.name
		)

	def get_customer(self, customer_name, contact):
		customer = frappe.db.get_value("Customer", {"customer_name": customer_name})
		if customer:
			return customer
		customer = (
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": customer_name,
					"customer_group": "_Test Customer Group",
					"territory": "_Test Territory",
				}
			)
			.insert()
			.name
		)
		frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": contact[0],
				"last_name": contact[1],
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		).insert()
		return customer

	def create_invoice(self, amount):
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": self.customer,
				"company": COMPANY,
				"set_posting_time": 1,
				"posting_date": PAYMENT_DATE,
				"due_date": PAYMENT_DATE,
				"debit_to": "Debtors - _TC",
				"currency": "INR",
				"conversion_rate": 1,
				"selling_price_list": "_Test Price List",
				"disable_rounded_total": 1,
				"items": [{"item_code": "_Test Item", "qty": 1, "rate": amount}],
			}
		)
		invoice.insert()
		invoice.submit()
		return invoice

	def create_receipt(self, amount, reference):
		payment = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": COMPANY,
				"party_type": "Customer",
				"party": self.customer,
				"posting_date": PAYMENT_DATE,
				"paid_to": "_Test Bank - _TC",
				"paid_amount": amount,
				"received_amount": amount,
				"reference_no": reference,
				"reference_date": PAYMENT_DATE,
			}
		)
		payment.setup_party_account_field()
		payment.set_missing_values()
		payment.insert()
		payment.submit()
		return payment

	def create_line(self, amount, description):
		"""A positive amount is money in."""
		return (
			frappe.get_doc(
				{
					"doctype": "Bank Transaction",
					"date": PAYMENT_DATE,
					"bank_account": self.bank_account,
					"credit": max(amount, 0),
					"debit": max(-amount, 0),
					"currency": "INR",
					"description": description,
				}
			)
			.insert()
			.submit()
		)

	def create_bank_fees_rule(self):
		account = frappe.db.get_value(
			"Account", {"company": COMPANY, "root_type": "Expense", "is_group": 0, "account_type": ""}
		)
		with self.set_user(ACCOUNTANT):
			return create_rule(
				self.create_line(-1, "FRAIS TENUE DE COMPTE AOUT").name, "Bank fees", "FRAIS TENUE", account
			)

	def pairing_of(self, line):
		with self.set_user(ACCOUNTANT):
			pairings = get_pairings(self.bank_account, str(PAYMENT_DATE), str(PAYMENT_DATE))["pairings"]
		return next(pairing for pairing in pairings if pairing["line"]["name"] == line.name)

	def test_an_invoice_paired_with_its_line_is_paid_on_validation(self):
		invoice = self.create_invoice(1234.56)
		line = self.create_line(1234.56, f"VIR SEPA RECU /DE JOHN DOE /MOTIF {invoice.name}")

		best = self.pairing_of(line)["proposals"][0]
		self.assertEqual(best["level"], "high")
		self.assertEqual(best["documents"][0]["name"], invoice.name)
		self.assertTrue(best["creates_payment"])

		with self.set_user(ACCOUNTANT):
			results = reconcile_pairings([{"bank_transaction": line.name, "documents": best["documents"]}])

		self.assertIsNone(results[0]["error"])
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 0)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 0)

	def test_undo_reopens_the_invoice_and_cancels_the_payment_it_created(self):
		invoice = self.create_invoice(765.43)
		line = self.create_line(765.43, f"VIR SEPA RECU /DE JOHN DOE /MOTIF {invoice.name}")
		documents = [{"doctype": "Sales Invoice", "name": invoice.name}]

		with self.set_user(ACCOUNTANT):
			[result] = reconcile_pairings([{"bank_transaction": line.name, "documents": documents}])
			[payment] = result["created"]
			self.assertEqual(payment["doctype"], "Payment Entry")
			undo_pairings([{"bank_transaction": line.name, "created": result["created"]}])

		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 765.43)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 765.43)
		self.assertEqual(frappe.db.get_value("Payment Entry", payment["name"], "docstatus"), 2)

	def test_a_rule_books_a_recurring_line_and_undo_cancels_the_entry(self):
		rule = self.create_bank_fees_rule()
		line = self.create_line(-12.5, "FRAIS TENUE DE COMPTE SEPTEMBRE")

		best = self.pairing_of(line)["proposals"][0]
		self.assertEqual(best["rule"]["name"], rule)
		with self.set_user(ACCOUNTANT):
			[result] = reconcile_pairings([{"bank_transaction": line.name, "rule": rule}])

		[entry] = result["created"]
		self.assertEqual(entry["doctype"], "Journal Entry")
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 0)

		with self.set_user(ACCOUNTANT):
			undo_pairings([{"bank_transaction": line.name, "created": result["created"]}])
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 12.5)
		self.assertEqual(frappe.db.get_value("Journal Entry", entry["name"], "docstatus"), 2)

	def test_one_line_pays_several_invoices(self):
		invoices = [self.create_invoice(amount) for amount in (111.11, 222.22)]
		line = self.create_line(333.33, "VIR SEPA RECU /DE JOHN DOE")

		with self.set_user(ACCOUNTANT):
			[result] = reconcile_pairings(
				[
					{
						"bank_transaction": line.name,
						"documents": [{"doctype": "Sales Invoice", "name": i.name} for i in invoices],
					}
				]
			)

		self.assertIsNone(result["error"])
		for invoice in invoices:
			self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 0)

	def test_an_invoice_finds_the_line_naming_it_first(self):
		invoice = self.create_invoice(543.21)
		unrelated = self.create_line(543.21, "VIR SEPA RECU /DE INCONNU")
		naming = self.create_line(543.21, f"VIR SEPA RECU /DE JOHN DOE /MOTIF {invoice.name}")

		with self.set_user(ACCOUNTANT):
			lines = get_lines_for_document("Sales Invoice", invoice.name)["lines"]

		self.assertEqual([match["line"]["name"] for match in lines[:2]], [naming.name, unrelated.name])
		self.assertEqual(lines[0]["proposal"]["level"], "high")

	def test_reconciling_from_the_invoice_pays_it(self):
		invoice = self.create_invoice(432.10)
		line = self.create_line(432.10, f"VIR JOHN DOE {invoice.name}")

		with self.set_user(ACCOUNTANT):
			reconcile_document("Sales Invoice", invoice.name, line.name)

		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 0)
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 0)

	def test_the_runner_up_invoice_stays_available_once_the_best_is_refused(self):
		best = self.create_invoice(456.78)
		runner_up = self.create_invoice(456.79)
		line = self.create_line(456.78, "VIR SEPA RECU /DE JOHN DOE")

		invoices = [p["documents"][0]["name"] for p in self.pairing_of(line)["proposals"]]

		self.assertEqual(invoices[:2], [best.name, runner_up.name])

	def test_a_card_batch_is_proposed_as_one_settlement_less_its_fee(self):
		receipts = [self.create_receipt(amount, f"TPE-{amount}") for amount in (130, 150, 120)]
		line = self.create_line(388, "REMISE CB 0000123")

		settlements = [p for p in self.pairing_of(line)["proposals"] if p.get("settlement")]

		self.assertEqual(len(settlements), 1)
		self.assertEqual(
			{d["name"] for d in settlements[0]["documents"]}, {receipt.name for receipt in receipts}
		)
		self.assertEqual(settlements[0]["settlement"]["fee"], 12)
		self.assertEqual(settlements[0]["level"], "low", "a fee-deducted batch is never confident")

	def test_a_refused_pairing_leaves_the_others_reconciled(self):
		invoice = self.create_invoice(321.09)
		paid_line = self.create_line(321.09, f"VIR JOHN DOE {invoice.name}")
		late_line = self.create_line(321.09, f"VIR JOHN DOE {invoice.name} BIS")
		documents = [{"doctype": "Sales Invoice", "name": invoice.name}]

		with self.set_user(ACCOUNTANT):
			results = reconcile_pairings(
				[
					{"bank_transaction": paid_line.name, "documents": documents},
					{"bank_transaction": late_line.name, "documents": documents},
				]
			)

		self.assertIsNone(results[0]["error"])
		self.assertIn("no longer open", results[1]["error"])
		self.assertEqual(frappe.db.get_value("Bank Transaction", paid_line.name, "unallocated_amount"), 0)
		self.assertEqual(
			frappe.db.get_value("Bank Transaction", late_line.name, "unallocated_amount"), 321.09
		)
