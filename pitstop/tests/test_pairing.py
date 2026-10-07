from datetime import date
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
	create_bulk_bank_entry_and_reconcile,
	create_bulk_payment_entry_and_reconcile,
)
from erpnext.accounts.doctype.bank_transaction.bank_transaction import PENDING_STATUS
from erpnext.accounts.page.bank_reconciliation.auto_bank_reconciliation import auto_bank_reconciliation
from erpnext.tests.utils import ERPNextTestSuite

from pitstop.api import (
	accept_rule_offer,
	create_rule,
	decline_rule_offer,
	get_pairings,
	get_period_totals,
	reconcile_pairings,
	set_refused_proposals,
	undo_pairings,
)
from pitstop.auto_reconciliation import (
	SETTING,
	get_auto_reconciliation,
	scheduled_reconciliation,
	set_auto_reconciliation,
)
from pitstop.lookup import get_lines_for_document, reconcile_document

PAYMENT_DATE = date(2026, 9, 15)
COMPANY = "_Test Company"
ACCOUNTANT = "pitstop-accountant@example.com"


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

	def create_invoice(self, amount, customer=None):
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": customer or self.customer,
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

	def create_receipt(self, amount, reference, customer=None):
		payment = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": COMPANY,
				"party_type": "Customer",
				"party": customer or self.customer,
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

	def create_line(self, amount, description, iban=None, status=None):
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
					"bank_party_iban": iban,
					"status": status,
				}
			)
			.insert()
			.submit()
		)

	def expense_accounts(self):
		return frappe.get_all(
			"Account",
			filters={"company": COMPANY, "root_type": "Expense", "is_group": 0, "account_type": ""},
			pluck="name",
			limit=2,
		)

	def create_bank_fees_rule(self):
		with self.set_user(ACCOUNTANT):
			return create_rule(
				self.create_line(-1, "FRAIS TENUE DE COMPTE AOUT").name,
				"Bank fees",
				"FRAIS TENUE",
				self.expense_accounts()[0],
			)

	def book_water_bills(self, account):
		"""Two water bills booked on the account from /banking, and the third one, still open."""
		for month in ("JUILLET", "AOUT"):
			line = self.create_line(-38.4, f"PRLV SEPA EAU FICTIVE CONTRAT 0042 {month}")
			with self.set_user(ACCOUNTANT):
				create_bulk_bank_entry_and_reconcile([line.name], account)
		return self.create_line(-41.75, "PRLV SEPA EAU FICTIVE CONTRAT 0042 SEPTEMBRE")

	def get_pairings(self):
		# Each call stands for a page load: the rules cached for the previous request are read again
		frappe.local.request_cache.clear()
		with self.set_user(ACCOUNTANT):
			return get_pairings(self.bank_account, str(PAYMENT_DATE), str(PAYMENT_DATE))

	def pairing_of(self, line):
		return next(pairing for pairing in self.get_pairings()["pairings"] if pairing["line"]["name"] == line.name)

	def rule_proposal_of(self, line):
		return next((p for p in self.pairing_of(line)["proposals"] if p.get("rule")), None)

	def rule_of(self, line):
		proposal = self.rule_proposal_of(line)
		return proposal and proposal["rule"]["name"]

	def run_hourly_job(self):
		# The job looks back from today; the fixtures are dated PAYMENT_DATE
		with patch("pitstop.auto_reconciliation.nowdate", return_value=str(PAYMENT_DATE)):
			scheduled_reconciliation()

	def by_document(self, line, field):
		"""Each single-document proposal of the line: document name -> the proposal's field."""
		proposals = self.pairing_of(line)["proposals"]
		return {p["documents"][0]["name"]: p[field] for p in proposals if len(p["documents"]) == 1}

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

	def test_period_totals_split_money_in_and_out_with_what_is_reconciled(self):
		invoice = self.create_invoice(500)
		paid = self.create_line(500, f"VIR SEPA RECU /DE JOHN DOE /MOTIF {invoice.name}")
		self.create_line(120, "VIR SEPA RECU /DE UNKNOWN")
		self.create_line(-80, "CB FICTIVE SHOP")
		self.create_line(40, "VIR ANNONCE", status=PENDING_STATUS)
		documents = [{"doctype": "Sales Invoice", "name": invoice.name}]
		with self.set_user(ACCOUNTANT):
			reconcile_pairings([{"bank_transaction": paid.name, "documents": documents}])
			totals = get_period_totals(self.bank_account, str(PAYMENT_DATE), str(PAYMENT_DATE))

		self.assertEqual(totals["in"], {"total": 620, "reconciled": 500, "lines": 2})
		self.assertEqual(totals["out"], {"total": 80, "reconciled": 0, "lines": 1})

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

	def test_invoices_of_two_parties_get_a_payment_each_and_undo_cancels_both(self):
		globex = self.get_customer("Globex Leasing", contact=("Jane", "Roe"))
		invoices = [self.create_invoice(150.5), self.create_invoice(249.5, customer=globex)]
		line = self.create_line(400, "VIR SEPA RECU /DE HOLDING DOE")
		documents = [{"doctype": "Sales Invoice", "name": invoice.name} for invoice in invoices]

		with self.set_user(ACCOUNTANT):
			[result] = reconcile_pairings([{"bank_transaction": line.name, "documents": documents}])

		self.assertIsNone(result["error"])
		payments = [voucher["name"] for voucher in result["created"]]
		self.assertEqual(
			{frappe.db.get_value("Payment Entry", payment, "party") for payment in payments},
			{self.customer, globex},
		)
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 0)

		with self.set_user(ACCOUNTANT):
			undo_pairings([{"bank_transaction": line.name, "created": result["created"]}])
		for invoice in invoices:
			self.assertEqual(
				frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), invoice.grand_total
			)

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

	def test_a_refused_lead_stays_refused_and_no_longer_blocks_its_rival(self):
		globex = self.get_customer("Globex Leasing", contact=("Jane", "Roe"))
		acme_invoice = self.create_invoice(612.40)
		globex_invoice = self.create_invoice(612.40, customer=globex)
		line = self.create_line(612.40, "VIR ACME RENTALS GLOBEX LEASING")

		self.assertEqual(self.by_document(line, "level")[globex_invoice.name], "medium", "two parties tie")
		with self.set_user(ACCOUNTANT):
			set_refused_proposals(line.name, [f"Sales Invoice:{acme_invoice.name}"])

		self.assertEqual(self.pairing_of(line)["refused"], [f"Sales Invoice:{acme_invoice.name}"])
		self.assertEqual(self.by_document(line, "level")[globex_invoice.name], "high")

	def test_a_correction_teaches_which_party_an_account_pays_for(self):
		globex = self.get_customer("Globex Leasing", contact=("Jane", "Roe"))
		acme_invoice = self.create_invoice(517.33)
		globex_invoice = self.create_invoice(517.33, customer=globex)
		first = self.create_line(
			517.33, "TRANSFER FROM ACCOUNT 4471", iban="FR76 3000 6000 0112 3456 7890 189"
		)
		documents = [{"doctype": "Sales Invoice", "name": globex_invoice.name}]
		with self.set_user(ACCOUNTANT):
			set_refused_proposals(first.name, [f"Sales Invoice:{acme_invoice.name}"])
			reconcile_pairings([{"bank_transaction": first.name, "documents": documents}])

		next_globex_invoice = self.create_invoice(517.33, customer=globex)
		# Not a word in common with the first label: only the account can tell who pays
		second = self.create_line(517.33, "INCOMING WIRE 9930", iban="FR7630006000011234567890189")

		scores = self.by_document(second, "score")
		self.assertGreater(scores[next_globex_invoice.name], 0.6, "the account's past payer gains")
		self.assertLess(scores[acme_invoice.name], 0.6, "the party corrected away loses")

		hints = {
			name: {reason["signal"]: reason["description"] for reason in documents[0]["reasons"]}
			for name, documents in self.by_document(second, "documents").items()
		}
		self.assertEqual(hints[next_globex_invoice.name]["history"], "Same account as past payments")
		self.assertIn("corrected", hints[acme_invoice.name], "a demoted lead says why")
		self.assertNotIn("corrected", hints[next_globex_invoice.name])

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

	def test_a_transfer_naming_its_payer_is_no_settlement_of_other_payers(self):
		globex = self.get_customer("Globex Leasing", contact=("Jane", "Roe"))
		for amount in (60.5, 60.5, 968, 968):
			self.create_receipt(amount, f"GLX-{amount}", customer=globex)
		acme_invoice = self.create_invoice(308.55)
		line = self.create_line(2057, "VERSEMENT INSTANTANE DE ACME RENTALS")

		proposals = self.pairing_of(line)["proposals"]

		self.assertEqual([p for p in proposals if p.get("settlement")], [], "Globex's receipts only add up")
		self.assertEqual(proposals[0]["documents"][0]["name"], acme_invoice.name)

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

	def test_a_line_the_bank_only_announced_is_neither_listed_nor_reconciled(self):
		invoice = self.create_invoice(654.32)
		pending = self.create_line(654.32, f"VIR JOHN DOE {invoice.name}", status=PENDING_STATUS)
		documents = [{"doctype": "Sales Invoice", "name": invoice.name}]

		self.assertNotIn(pending.name, [p["line"]["name"] for p in self.get_pairings()["pairings"]])
		with self.set_user(ACCOUNTANT):
			found = get_lines_for_document("Sales Invoice", invoice.name)["lines"]
			[result] = reconcile_pairings([{"bank_transaction": pending.name, "documents": documents}])

		self.assertNotIn(pending.name, [match["line"]["name"] for match in found])
		self.assertIn("only announced", result["error"])
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 654.32)

	def test_the_hourly_job_reconciles_a_line_naming_its_invoice_once_enabled(self):
		invoice = self.create_invoice(432.1)
		line = self.create_line(432.1, f"VIR SEPA RECU /DE JOHN DOE /MOTIF {invoice.name}")

		self.run_hourly_job()
		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 432.1, "off by default")

		with self.set_user(ACCOUNTANT):
			self.assertTrue(get_auto_reconciliation()["can_change"])
			set_auto_reconciliation(True)
		self.run_hourly_job()

		self.assertEqual(frappe.db.get_value("Bank Transaction", line.name, "unallocated_amount"), 0)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 0)

	def test_a_line_the_hourly_job_fails_on_is_logged_and_the_others_still_reconcile(self):
		failing, working = (self.create_invoice(amount) for amount in (111.11, 222.22))
		failing_line = self.create_line(111.11, f"VIR JOHN DOE {failing.name}")
		working_line = self.create_line(222.22, f"VIR JOHN DOE {working.name}")
		frappe.db.set_single_value("Accounts Settings", SETTING, 1)

		def crash_on_failing_line(rows):
			if frappe.parse_json(rows)[0]["name"] == failing_line.name:
				raise RuntimeError("Simulated crash")
			return auto_bank_reconciliation(rows)

		with patch("pitstop.auto_reconciliation.auto_bank_reconciliation", side_effect=crash_on_failing_line):
			self.run_hourly_job()

		self.assertEqual(frappe.db.get_value("Bank Transaction", failing_line.name, "unallocated_amount"), 111.11)
		self.assertEqual(frappe.db.get_value("Bank Transaction", working_line.name, "unallocated_amount"), 0)
		self.assertTrue(frappe.db.exists("Error Log", {"reference_name": failing_line.name}))

	def test_a_label_always_booked_on_one_account_is_offered_as_a_rule(self):
		account = self.expense_accounts()[0]
		line = self.book_water_bills(account)

		[offer] = self.get_pairings()["rule_offers"]
		self.assertEqual((offer["account"], offer["booked"], offer["lines"]), (account, 2, [line.name]))
		with self.set_user(ACCOUNTANT):
			rule = accept_rule_offer(self.bank_account, offer["key"], offer["transaction_type"])

		self.assertEqual(self.rule_of(line), rule)
		self.assertEqual(self.get_pairings()["rule_offers"], [], "an accepted offer is not made again")

	def test_a_label_always_paid_by_one_party_is_offered_as_a_payment_rule_that_yields_to_its_invoices(self):
		label = "VIR SEPA RECU /DE HOLDING FICTIVE /MOTIF ABONNEMENT {}"
		for month in ("JUILLET", "AOUT"):
			line = self.create_line(845.5, label.format(month))
			with self.set_user(ACCOUNTANT):
				create_bulk_payment_entry_and_reconcile([line.name], "Customer", self.customer, "Debtors - _TC")
		line = self.create_line(845.5, label.format("SEPTEMBRE"))

		[offer] = self.get_pairings()["rule_offers"]
		self.assertEqual(
			(offer["classify_as"], offer["party"], offer["account"]),
			("Payment Entry", self.customer, "Debtors - _TC"),
		)
		with self.set_user(ACCOUNTANT):
			rule = accept_rule_offer(self.bank_account, offer["key"], offer["transaction_type"])
		self.assertEqual(self.rule_proposal_of(line)["level"], "high")

		self.create_invoice(900)
		proposal = self.rule_proposal_of(line)
		self.assertEqual((proposal["rule"]["name"], proposal["level"]), (rule, "low"), "its party's invoice comes first")

	def test_a_label_that_paid_invoices_gets_no_payment_rule(self):
		label = "VIR SEPA RECU /DE HOLDING FICTIVE /MOTIF ABONNEMENT {}"
		for month in ("JUILLET", "AOUT"):
			documents = [{"doctype": "Sales Invoice", "name": self.create_invoice(845.5).name}]
			line = self.create_line(845.5, label.format(month))
			with self.set_user(ACCOUNTANT):
				reconcile_pairings([{"bank_transaction": line.name, "documents": documents}])
		self.create_line(845.5, label.format("SEPTEMBRE"))

		self.assertEqual(self.get_pairings()["rule_offers"], [], "the scorer finds its next invoice without a rule")

	def test_a_declined_rule_offer_books_nothing_and_never_comes_back(self):
		line = self.book_water_bills(self.expense_accounts()[0])

		[offer] = self.get_pairings()["rule_offers"]
		with self.set_user(ACCOUNTANT):
			decline_rule_offer(self.bank_account, offer["key"], offer["transaction_type"])

		self.assertEqual(self.get_pairings()["rule_offers"], [])
		self.assertIsNone(self.rule_of(line))

	def test_a_rule_the_forecast_only_proposed_books_nothing_until_accepted(self):
		booked_on, guessed = self.expense_accounts()
		line = self.book_water_bills(booked_on)
		proposed = frappe.get_doc(
			{
				"doctype": "Bank Transaction Rule",
				"rule_name": "Recurring: EAU FICTIVE CONTRAT",
				"company": COMPANY,
				"transaction_type": "Withdrawal",
				"classify_as": "Bank Entry",
				"bank_entry_type": "Single Account",
				"account": guessed,
				"description_rules": [{"check": "Contains", "value": "eau fictive"}],
				"proposal_status": "Proposed",
				"detected_from_description": "EAU FICTIVE CONTRAT",
			}
		).insert()

		self.assertIsNone(self.rule_of(line))
		[offer] = self.get_pairings()["rule_offers"]
		with self.set_user(ACCOUNTANT):
			rule = accept_rule_offer(self.bank_account, offer["key"], offer["transaction_type"])

		self.assertEqual(rule, proposed.name, "the forecast's proposal carries the answer")
		self.assertEqual(
			frappe.db.get_value("Bank Transaction Rule", rule, ["proposal_status", "account"]),
			("Accepted", booked_on),
		)
		self.assertEqual(self.rule_of(line), rule)
