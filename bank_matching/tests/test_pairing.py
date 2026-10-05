from datetime import date

import frappe
from erpnext.tests.utils import ERPNextTestSuite

from bank_matching.api import get_pairings, reconcile_pairings

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
		return (
			frappe.get_doc(
				{
					"doctype": "Bank Transaction",
					"date": PAYMENT_DATE,
					"bank_account": self.bank_account,
					"credit": amount,
					"currency": "INR",
					"description": description,
				}
			)
			.insert()
			.submit()
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

		self.assertEqual(results, [{"bank_transaction": line.name, "error": None}])
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 0)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 0)

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
