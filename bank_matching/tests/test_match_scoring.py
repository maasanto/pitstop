from datetime import date

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.page.bank_reconciliation.bank_transaction_match import BankTransactionMatch
from erpnext.tests.utils import ERPNextTestSuite

from bank_matching.match_scoring import (
	ONE_TYPO,
	YEAR_AND_COUNTER,
	Receipt,
	Reference,
	Vocabulary,
	amount_grade,
	is_identifier,
	name_grade,
	reference_evidence,
	settlement_batches,
)
from bank_matching.ranking import SuggestionRanking, payer

PAYMENT_DATE = date(2026, 9, 15)
INVOICES = [
	Reference.parse("SINV-123", "ACC-SINV-2026-00123"),
	Reference.parse("SINV-124", "ACC-SINV-2026-00124"),
	Reference.parse("SINV-131", "ACC-SINV-2026-00131"),
	Reference.parse("SINV-2025-123", "ACC-SINV-2025-00123"),
	Reference.parse("SINV-4567", "ACC-SINV-2026-04567"),
	Reference.parse("PAY-1", "ACC-PAY-2025-00001"),
]


def best_reference(label, references=INVOICES):
	evidence = reference_evidence(label, references, 200.10, [PAYMENT_DATE])
	return evidence, max(evidence, key=evidence.get) if evidence else None


class TestReferenceSearch(ERPNextTestSuite):
	def test_typed_invoice_numbers_are_found_despite_typos(self):
		self.assertEqual(best_reference("VIR JOHN DOE /MOTIF ACC-SINV-2026-00123")[1], "SINV-123")
		self.assertEqual(best_reference("JOHN DOE FACTURE SINV 2026 123")[1], "SINV-123")
		self.assertEqual(best_reference("JOHN DOE ACCSINV20260124")[0], {"SINV-124": YEAR_AND_COUNTER})
		self.assertEqual(best_reference("JOHN DOE ACC SINV 2026 04576")[0], {"SINV-4567": ONE_TYPO})

	def test_a_typo_between_two_invoices_points_at_neither(self):
		evidence, _ = best_reference("JOHN DOE ACC-SINV-2026-00133")
		self.assertEqual(set(evidence), {"SINV-123", "SINV-131"})
		self.assertTrue(all(value < ONE_TYPO for value in evidence.values()))

	def test_dates_amounts_and_other_series_are_not_references(self):
		self.assertNotIn("PAY-1", best_reference("JOHN DOE LOYER 25/01/2026")[0])
		self.assertEqual(best_reference("JOHN DOE PAIEMENT 15092026 20010")[0], {})
		# Another series' number is at most a bare-counter hint, which needs an amount or a name to count
		other_series = reference_evidence("ACC-PAY-2026-00123", INVOICES, 1, [PAYMENT_DATE])
		self.assertLess(other_series.get("SINV-123", 0), YEAR_AND_COUNTER)

	def test_a_number_is_not_found_inside_a_longer_one(self):
		unpadded = [Reference.parse("FA-1", "FA-2026-1"), Reference.parse("FA-12", "FA-2026-12")]
		self.assertEqual(
			set(reference_evidence("JOHN DOE FA-2026-12", unpadded, 1, [PAYMENT_DATE])), {"FA-12"}
		)

	def test_an_amended_invoice_keeps_its_original_counter(self):
		amended = Reference.parse("SINV-123-1", "ACC-SINV-2026-00123-1")
		self.assertEqual(amended.counter, "123")
		evidence = reference_evidence("FACTURE ACC-SINV-2026-00001", [amended], 1, [PAYMENT_DATE])
		self.assertEqual(evidence, {})

	def test_a_reference_repeated_in_many_labels_identifies_nothing(self):
		standing_order_labels = [f"VIRPERMANENTLOYERAPPT12MARS{month}" for month in range(12)]
		self.assertFalse(is_identifier("LOYER APPT12", standing_order_labels))
		self.assertTrue(is_identifier("CHQ 1234567", standing_order_labels))

	def test_a_transfer_reference_is_an_identifier_but_a_pasted_label_is_not(self):
		self.assertTrue(is_identifier("VIR-IL-0042", []))
		self.assertFalse(is_identifier("VIR SEPA EMIS IMPRIMERIE LAMBDA 0042", []))


class TestSignalGrades(ERPNextTestSuite):
	def test_amount_tolerates_typing_slips_and_float_noise(self):
		self.assertEqual(amount_grade(314.41 - 260.29, 54.12, 54.12), 1.0)
		self.assertEqual(amount_grade(200, 200.10, 200.10), 0.7)
		self.assertEqual(amount_grade(1520, 1250, 1250), 0.4)
		self.assertEqual(amount_grade(500, 200.10, 200.10), 0.0)
		self.assertEqual(amount_grade(10, 100, 100), 0.0, "a missing digit is a tenfold difference")
		self.assertEqual(amount_grade(0, 5, 5), 0.0)

	def test_names_and_codes_count_only_when_they_identify_one_party(self):
		vocabulary = Vocabulary([], ["Jean Martin", "Garage Martin", "Martin Dupont"])

		def grade(label, party, party_name, bank_party_name=None):
			return name_grade(
				label, vocabulary.label_words(label), bank_party_name, party, party_name, [], vocabulary
			)

		self.assertLess(grade("VIR SEPA", "Jean Martin", "Jean Martin", bank_party_name="MARTIN"), 1.0)
		self.assertEqual(grade("VIR SEPA", "Jean Martin", "Jean Martin", bank_party_name="MARTIN JEAN"), 1.0)
		self.assertEqual(grade("VIR CUST00042 LOYER", "CUST-00042", "Acme Rentals"), 1.0)
		self.assertEqual(grade("VIR PAULO RENT", "Loren", "Loren"), 0.0)

	def test_documents_without_a_party_never_share_one(self):
		first = frappe._dict(doctype="Journal Entry", name="JV-1", party_type=None, party=None)
		second = frappe._dict(doctype="Journal Entry", name="JV-2", party_type=None, party=None)
		self.assertNotEqual(payer(first), payer(second))

	def test_a_regular_payer_name_stays_identifying(self):
		labels = [f"VIR SEPA RECU BAZAAR DURAND LOYER {month}" for month in range(50)]
		parties = ["Pierre Durand", "Bazaar Lille", "Bazaar Roubaix", "Bazaar Tourcoing"]
		vocabulary = Vocabulary(labels, parties)
		self.assertTrue(vocabulary.is_identifying("DURAND"))
		self.assertFalse(vocabulary.is_identifying("BAZAAR"))
		self.assertFalse(vocabulary.is_identifying("SEPA"))


class TestSettlements(ERPNextTestSuite):
	def receipts(self, *rows):
		return [
			Receipt(f"PAY-{index}", amount, date(2026, 9, day), mode)
			for index, (amount, day, mode) in enumerate(rows)
		]

	def test_a_card_batch_is_paid_out_whole_or_less_its_fee(self):
		receipts = self.receipts((100, 14, "Card"), (120, 14, "Card"), (80, 14, "Card"), (300, 14, "Cheque"))
		self.assertEqual(settlement_batches(300, PAYMENT_DATE, receipts)[0].keys, ("PAY-0", "PAY-1", "PAY-2"))
		less_fees = settlement_batches(291.30, PAYMENT_DATE, receipts)
		self.assertEqual(less_fees[0].keys, ("PAY-0", "PAY-1", "PAY-2"))
		self.assertEqual(less_fees[0].fee, 8.70)

	def test_a_deposit_of_consecutive_receipts_sums_up_exactly(self):
		receipts = self.receipts((40, 1, "Cheque"), (60, 3, "Cash"), (25, 9, "Cheque"), (500, 10, "Cheque"))
		self.assertEqual(settlement_batches(125, PAYMENT_DATE, receipts)[0].keys, ("PAY-0", "PAY-1", "PAY-2"))

	def test_receipts_posted_after_the_payout_or_a_lone_receipt_are_no_batch(self):
		self.assertEqual(
			settlement_batches(200, PAYMENT_DATE, self.receipts((100, 14, "Card"), (100, 16, "Card"))), []
		)
		self.assertEqual(settlement_batches(100, PAYMENT_DATE, self.receipts((100, 14, "Card"))), [])


class TestSuggestions(ERPNextTestSuite):
	def setUp(self):
		super().setUp()
		self.company = "_Test Company"
		self.bank_account = self.get_bank_account()
		self.customer = self.get_customer("Acme Rentals", contact=("John", "Doe"))

	def get_bank_account(self):
		if not frappe.db.exists("Bank", "_Test Bank"):
			frappe.get_doc({"doctype": "Bank", "bank_name": "_Test Bank"}).insert()
		existing = frappe.db.get_value("Bank Account", {"account": "_Test Bank - _TC", "bank": "_Test Bank"})
		if existing:
			return existing
		return (
			frappe.get_doc(
				{
					"doctype": "Bank Account",
					"account_name": "_Test Bank Account",
					"account": "_Test Bank - _TC",
					"company": self.company,
					"bank": "_Test Bank",
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

	def create_invoice(self, customer, amount, po_no=None):
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": customer,
				"po_no": po_no,
				"company": self.company,
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

	def suggest(self, amount, description):
		line = {
			"name": "BT-SUGGESTION-TEST",
			"amount": amount,
			"currency": "INR",
			"bank_account": self.bank_account,
			"date": str(PAYMENT_DATE),
			"description": description,
		}
		return SuggestionRanking(BankTransactionMatch([line], None)).rank()

	def test_a_typed_number_a_close_amount_and_a_contact_preselect_the_invoice(self):
		invoice = self.create_invoice(self.customer, 200.10)
		self.create_invoice("_Test Customer", 200.10)

		best = self.suggest(200, f"VIR SEPA RECU /DE JOHN DOE /MOTIF FACTURE {invoice.name}")[0]

		self.assertEqual((best.doctype, best.name), ("Sales Invoice", invoice.name))
		self.assertTrue(best.vgtSelected)
		# A contact, not the party name, is an approximate name signal
		self.assertIn(
			{"signal": "name", "exact": False, "description": "Contact in the label"}, best.match_reasons
		)

	def test_the_order_number_of_a_paid_invoice_points_at_its_open_payment(self):
		invoice = self.create_invoice(self.customer, 300, po_no="PO-ACME-7781")
		payment = get_payment_entry("Sales Invoice", invoice.name, bank_account="_Test Bank - _TC")
		payment.update({"posting_date": PAYMENT_DATE, "reference_no": "DEP-1", "reference_date": PAYMENT_DATE})
		payment.insert()
		payment.submit()

		suggestions = self.suggest(300, "VIR SEPA RECU PO-ACME-7781")

		suggested = next(d for d in suggestions if d.name == payment.name)
		self.assertIn("reference", [reason["signal"] for reason in suggested.match_reasons])

	def test_a_journal_entry_is_found_by_its_cheque_number(self):
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": self.company,
				"posting_date": PAYMENT_DATE,
				"cheque_no": "CHQ-5512",
				"cheque_date": PAYMENT_DATE,
				"accounts": [
					{"account": "_Test Bank - _TC", "debit_in_account_currency": 75},
					{
						"account": "Debtors - _TC",
						"party_type": "Customer",
						"party": self.customer,
						"credit_in_account_currency": 75,
					},
				],
			}
		).insert()
		entry.submit()

		suggestions = self.suggest(75, "REMISE CHEQUE CHQ-5512")

		suggested = next(d for d in suggestions if d.name == entry.name)
		self.assertIn("reference", [reason["signal"] for reason in suggested.match_reasons])

	def test_documents_moving_money_the_other_way_are_never_suggested(self):
		invoice = self.create_invoice(self.customer, 200.10)

		suggestions = self.suggest(-200.10, f"PRLV JOHN DOE {invoice.name}")

		self.assertNotIn(invoice.name, [d.name for d in suggestions])

	def test_an_exact_amount_alone_is_suggested_but_not_preselected(self):
		invoice = self.create_invoice(self.customer, 4321.09)

		suggestions = self.suggest(4321.09, "VIR SEPA RECU")

		self.assertIn(invoice.name, [d.name for d in suggestions])
		self.assertFalse(any(d.get("vgtSelected") for d in suggestions))

	def test_an_accountant_without_hr_roles_still_gets_suggestions(self):
		# Expense Claims are unreadable to a plain accountant: they are skipped, not an error
		invoice = self.create_invoice(self.customer, 200.10)
		if not frappe.db.exists("User", "accountant@example.com"):
			user = frappe.get_doc(
				{"doctype": "User", "email": "accountant@example.com", "first_name": "Accountant"}
			).insert()
			user.add_roles("Accounts User")

		with self.set_user("accountant@example.com"):
			suggestions = self.suggest(200.10, f"VIR JOHN DOE {invoice.name}")

		self.assertIn(invoice.name, [d.name for d in suggestions])

	def test_nothing_is_suggested_when_no_signal_fires(self):
		self.assertEqual(self.suggest(9876.54, "VIR SEPA RECU"), [])
