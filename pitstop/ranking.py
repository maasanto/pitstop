"""Every open document scored against a bank line, best first.

Ported from the erpnext branch feat/bank-rec-match-scoring so the app runs on a stock erpnext; the scoring
moves back into core once the page is settled.
"""

import frappe
from erpnext.accounts.page.bank_reconciliation.bank_transaction_match import (
	PARTY_FIELD,
	PARTY_TYPES,
	BankTransactionMatch,
)
from frappe import _
from frappe.utils import add_days, flt, getdate

from pitstop.match_scoring import (
	MAX_DAYS_POSTED_AFTER_PAYMENT,
	PRESELECT_LEAD,
	PRESELECT_THRESHOLD,
	SHOW_THRESHOLD,
	WEAK_REFERENCE,
	YEAR_AND_COUNTER,
	PastLine,
	Reference,
	Vocabulary,
	account_parties,
	amount_grade,
	confidence,
	counterparty_account,
	is_damped,
	is_identifier,
	is_posted_after_payment,
	name_grade,
	normalize,
	reference_evidence,
	shared_accounts,
	similar_line_parties,
)

DOCUMENT_TYPES = ("Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice", "Expense Claim")
LOOK_BACK_DAYS = 365
# An amount alone matches too many documents: it needs another signal, or a document dated near the line.
# Most invoices reconciled on production sites were paid within this window of their posting date; past
# MAX_DAYS_POSTED_AFTER_PAYMENT, scoring also damps a document backed by other signals.
AMOUNT_ALONE_DAYS_BEFORE = 30
CORROBORATING_SIGNALS = {"reference", "name", "history"}
# The number the other side writes in its transfer label, next to the document's own name
EXTRA_NUMBER_FIELD = {
	"Payment Entry": "reference_no",
	"Sales Invoice": "po_no",
	"Purchase Invoice": "bill_no",
}


class AccountContext:
	"""What scoring reads about a bank account, the same for each of its lines: loaded once for a batch of lines.

	The account's labels and history cover a year before the batch's oldest line, so a newer line of the batch
	sees a few more months of them than it would scored alone.
	"""

	def __init__(self, bank_transactions):
		self.matcher = BankTransactionMatch(bank_transactions[:1], None)
		dates = [getdate(t.get("date")) for t in bank_transactions if t.get("date")]
		self.since = add_days(min(dates, default=getdate()), -LOOK_BACK_DAYS)
		self.candidates = self.get_candidates()
		self.account_lines = self.get_account_lines()
		self.contacts = get_contacts()
		self.vocabulary = Vocabulary(
			[line.label for line in self.account_lines], get_party_names(self.contacts)
		)
		self.references = self.get_references()
		self.history, self.corrections = self.get_history()

	def get_candidates(self):
		"""Open documents of every type, with the amount they move into the bank or out of it."""
		candidates = []
		for document_type in DOCUMENT_TYPES:
			if not frappe.db.exists("DocType", document_type) or not frappe.has_permission(
				document_type, "read"
			):
				continue
			matcher = BankTransactionMatch(self.matcher.bank_transactions, document_type, match=False)
			for row in matcher.get_linked_documents():
				candidate = frappe._dict(row, doctype=document_type, **describe_document(document_type, row))
				if candidate.signed_amount:
					candidates.append(candidate)
		journal_entries = [c for c in candidates if c.doctype == "Journal Entry"]
		set_journal_entry_parties(journal_entries)
		add_cheque_numbers(journal_entries)
		return candidates

	def get_account_lines(self):
		"""The bank account's lines over the look-back period, labels normalized for comparison."""
		lines = frappe.get_all(
			"Bank Transaction",
			filters={
				"bank_account": self.matcher.bank_account,
				"docstatus": 1,
				"date": (">=", self.since),
			},
			fields=[
				"name",
				"description",
				"reference_number",
				"bank_party_name",
				"bank_party_iban",
				"bank_party_account_number",
				"allocated_amount",
			],
		)
		for line in lines:
			line.label = " ".join(
				filter(None, (line.description, line.reference_number, line.bank_party_name))
			)
			line.compact_label = normalize(line.label).replace(" ", "")
			line.account = counterparty_account(line.bank_party_iban, line.bank_party_account_number)
		return lines

	def get_references(self):
		"""Document numbers to look for in the label: the candidates', and recent closed invoices'.

		An invoice already settled by an open payment is found through that payment.
		"""
		candidates = self.candidates
		compact_labels = [line.compact_label for line in self.account_lines]
		references = [
			Reference.parse(candidate.name, number)
			for candidate in candidates
			for number in candidate.numbers
			if number and (number == candidate.name or is_identifier(number, compact_labels))
		]
		open_names = {candidate.name for candidate in candidates}
		held_by_payment = {
			row.reference_name: row.parent
			for row in frappe.get_all(
				"Payment Entry Reference",
				filters={
					"parent": ("in", [c.name for c in candidates if c.doctype == "Payment Entry"] or [""])
				},
				fields=["parent", "reference_name"],
			)
			if row.reference_name not in open_names
		}
		for doctype in ("Sales Invoice", "Purchase Invoice"):
			number_field = EXTRA_NUMBER_FIELD[doctype]
			for invoice in frappe.get_all(
				doctype,
				filters={"docstatus": 1, "company": self.matcher.company, "posting_date": (">=", self.since)},
				fields=["name", number_field],
			):
				key = held_by_payment.get(invoice.name, invoice.name)
				references.append(Reference.parse(key, invoice.name))
				number = invoice.get(number_field)
				if number and is_identifier(number, compact_labels):
					references.append(Reference.parse(key, number))
		return references

	def get_history(self):
		"""The account's lines already reconciled, twice, by line: with the parties they went to, and with the
		parties the user refused on them before choosing another."""
		reconciled = {line.name: line for line in self.account_lines if line.allocated_amount}
		links = frappe.get_all(
			"Bank Transaction Payments",
			filters={"parenttype": "Bank Transaction", "parent": ("in", list(reconciled) or [""])},
			fields=["parent", "payment_document", "payment_entry"],
		)
		party_of = get_document_parties(links)
		parties_by_line = {}
		for link in links:
			party_type, party = party_of.get((link.payment_document, link.payment_entry), (None, None))
			if party:
				parties_by_line.setdefault(link.parent, set()).add((party_type, party))

		def past_lines(parties_by):
			return {
				name: PastLine(
					frozenset(self.vocabulary.label_words(reconciled[name].label)),
					reconciled[name].account,
					frozenset(parties),
				)
				for name, parties in parties_by.items()
			}

		return past_lines(parties_by_line), past_lines(get_corrections(parties_by_line))


class SuggestionRanking:
	"""Score every open document of every type against the selected bank lines, best first."""

	def __init__(self, bank_transaction_match, context: AccountContext | None = None):
		self.matcher = bank_transaction_match
		transactions = bank_transaction_match.bank_transactions
		self.context = context or AccountContext(transactions)
		self.amount = flt(bank_transaction_match.amount, 2)
		self.label = " ".join(
			filter(
				None,
				(
					t.get(field)
					for t in transactions
					for field in ("description", "reference_number", "bank_party_name")
				),
			)
		)
		self.bank_party_name = transactions[0].get("bank_party_name")
		self.account = counterparty_account(
			transactions[0].get("bank_party_iban"), transactions[0].get("bank_party_account_number")
		)
		self.dates = [getdate(t.get("date")) for t in transactions if t.get("date")]
		self.selected = {t.get("name") for t in transactions}

	def rank(self, refused=()):
		"""Suggestions best first; `refused` proposal keys stay listed but never preselected."""
		context = self.context
		# Copies: scoring writes onto them, and the context serves every line of the batch.
		# Kept for callers that also look for settlements among documents too weak to suggest alone.
		self.candidates = candidates = [
			frappe._dict(candidate)
			for candidate in context.candidates
			if (candidate.signed_amount > 0) == (self.amount > 0)
		]
		if not candidates:
			return []

		contacts, vocabulary = context.contacts, context.vocabulary
		label_words = vocabulary.label_words(self.label)
		evidence = reference_evidence(self.label, context.references, self.amount, self.dates)
		history = self.others(context.history)
		corrections = self.others(context.corrections)
		ignored_accounts = shared_accounts(history)
		learned = frappe._dict(
			payers=similar_line_parties(label_words, self.account, history, ignored_accounts),
			corrected=similar_line_parties(label_words, self.account, corrections, ignored_accounts),
			account_payers=account_parties(self.account, history, ignored_accounts),
		)
		for candidate in candidates:
			self.score(candidate, evidence, label_words, vocabulary, learned, contacts)

		suggestions = sorted(
			(c for c in candidates if c.match_score >= SHOW_THRESHOLD and self.is_corroborated(c)),
			key=lambda c: (-c.match_score, self.days_apart(c)),
		)
		self.preselect([s for s in suggestions if proposal_key(s) not in refused])
		return suggestions

	def score(self, candidate, evidence, label_words, vocabulary, learned, contacts):
		party = (candidate.party_type, candidate.party)
		signals = frappe._dict(
			reference=evidence.get(candidate.name, 0),
			amount=amount_grade(self.amount, candidate.signed_amount, candidate.grand_total),
			name=name_grade(
				self.label,
				label_words,
				self.bank_party_name,
				candidate.party,
				candidate.party_name,
				contacts.get(party, []),
				vocabulary,
			),
			history=learned.payers.get(party, 0),
			corrected=learned.corrected.get(party, 0),
			days_after=self.days_after(candidate),
		)
		if signals.reference < WEAK_REFERENCE and not (signals.amount or signals.name or signals.history):
			signals.reference = 0
		candidate.match_score = flt(confidence(**signals), 3)
		candidate.match_reasons = describe_signals(
			frappe._dict(signals, same_account=party in learned.account_payers, is_near=self.is_near(candidate))
		)

	def preselect(self, suggestions):
		if not suggestions or suggestions[0].match_score < PRESELECT_THRESHOLD:
			return
		best = suggestions[0]
		other_parties = [s.match_score for s in suggestions if payer(s) != payer(best)]
		if flt(best.match_score - max(other_parties, default=0), 3) >= PRESELECT_LEAD:
			best.vgtSelected = True

	def is_corroborated(self, candidate):
		if any(reason["signal"] in CORROBORATING_SIGNALS for reason in candidate.match_reasons):
			return True
		return self.is_near(candidate)

	def is_near(self, candidate):
		if not self.dates or not candidate.posting_date:
			return False
		return -AMOUNT_ALONE_DAYS_BEFORE <= self.days_after(candidate) <= MAX_DAYS_POSTED_AFTER_PAYMENT

	def days_apart(self, candidate):
		if not self.dates or not candidate.posting_date:
			return LOOK_BACK_DAYS
		return abs((getdate(candidate.posting_date) - self.dates[0]).days)

	def days_after(self, candidate):
		"""How long after the latest selected line the document was posted, negative when before."""
		if not self.dates or not candidate.posting_date:
			return 0
		return (getdate(candidate.posting_date) - max(self.dates)).days

	def others(self, past_lines: dict) -> list:
		"""The past lines but the ones being scored: a line teaches nothing about itself."""
		return [past for name, past in past_lines.items() if name not in self.selected]


def get_corrections(parties_by_line):
	"""Line -> parties the user refused on it, then reconciled it with another party.

	A refusal of the party the line went to anyway says "wrong document", not "wrong party": it teaches nothing.
	"""
	corrections = {}
	for refusal in frappe.get_all(
		"Bank Match Refusal",
		filters={"bank_transaction": ("in", list(parties_by_line) or [""]), "party": ("is", "set")},
		fields=["bank_transaction", "party_type", "party"],
	):
		party = (refusal.party_type, refusal.party)
		if party not in parties_by_line[refusal.bank_transaction]:
			corrections.setdefault(refusal.bank_transaction, set()).add(party)
	return corrections


def proposal_key(document):
	return f"{document.doctype}:{document.name}"


def payer(document):
	"""Who the money comes from or goes to; a document without a party stands alone."""
	return (document.party_type, document.party) if document.party else (document.doctype, document.name)


def get_journal_entry_parties(names):
	"""Journal entry -> (party type, party) of its first line with a party: the bank line has none."""
	parties = {}
	for line in frappe.get_all(
		"Journal Entry Account",
		filters={"parent": ("in", list(names) or [""]), "party": ("is", "set")},
		fields=["parent", "party_type", "party"],
		order_by="idx",
	):
		parties.setdefault(line.parent, (line.party_type, line.party))
	return parties


def set_journal_entry_parties(journal_entries):
	parties = get_journal_entry_parties({je.name for je in journal_entries})
	for journal_entry in journal_entries:
		party_type, party = parties.get(journal_entry.name, (None, None))
		if party:
			journal_entry.update(party_type=party_type, party=party, party_name=party)


def add_cheque_numbers(journal_entries):
	"""erpnext's journal entry rows carry the cheque number only inside their display string."""
	cheque_numbers = dict(
		frappe.get_all(
			"Journal Entry",
			filters={"name": ("in", [je.name for je in journal_entries] or [""]), "cheque_no": ("is", "set")},
			fields=["name", "cheque_no"],
			as_list=True,
		)
	)
	for journal_entry in journal_entries:
		journal_entry.numbers.append(cheque_numbers.get(journal_entry.name))


# ponytail: customers, suppliers and contacts are read on every suggestion request; cache them per
# site if large sites feel it.
def get_contacts():
	"""(party type, party) -> [(first name, last name)] for contacts of customers and suppliers."""
	contacts = {}
	for row in frappe.get_all(
		"Contact",
		filters=[["Dynamic Link", "link_doctype", "in", ["Customer", "Supplier"]]],
		fields=["first_name", "last_name", "`tabDynamic Link`.link_doctype", "`tabDynamic Link`.link_name"],
	):
		contacts.setdefault((row.link_doctype, row.link_name), []).append(
			(row.first_name or "", row.last_name or "")
		)
	return contacts


def get_party_names(contacts):
	"""Each customer's and supplier's name, followed by its contacts' names."""
	names = []
	for party_type, field in (("Customer", "customer_name"), ("Supplier", "supplier_name")):
		for party in frappe.get_all(party_type, fields=["name", field]):
			contact_names = " ".join(
				f"{first} {last}" for first, last in contacts.get((party_type, party.name), [])
			)
			names.append(f"{party.get(field) or party.name} {contact_names}")
	return names


def describe_document(document_type, row):
	"""The fields scoring needs, the same for every document type."""
	if document_type == "Journal Entry":
		into_bank = flt(row.get("debit_in_account_currency")) > flt(row.get("credit_in_account_currency"))
		amount = flt(row.get("amount"))
		return dict(
			signed_amount=amount if into_bank else -amount,
			grand_total=amount,
			party_type=row.get("party_type"),
			party=row.get("party"),
			party_name=row.get("party"),
			numbers=[row.get("name")],
		)
	if document_type == "Expense Claim":
		return dict(
			signed_amount=-abs(flt(row.get("amount"))),
			grand_total=flt(row.get("total_sanctioned_amount")),
			party_type="Employee",
			party=row.get("employee"),
			party_name=row.get("employee_name"),
			numbers=[row.get("name")],
		)
	party_type = PARTY_TYPES.get(document_type, row.get("party_type"))
	return dict(
		signed_amount=flt(row.get("amount")),
		grand_total=flt(row.get("rounded_total") or row.get("grand_total") or row.get("paid_amount")),
		party_type=party_type,
		party=row.get("party"),
		party_name=row.get("party_name"),
		numbers=[row.get("name"), row.get(EXTRA_NUMBER_FIELD[document_type])],
	)


def get_document_parties(links):
	"""(document type, name) -> (party type, party) for documents linked to reconciled bank lines."""
	names_by_type = {}
	for link in links:
		names_by_type.setdefault(link.payment_document, set()).add(link.payment_entry)
	parties = {}
	for document_type, names in names_by_type.items():
		filters = {"name": ("in", list(names))}
		if document_type == "Payment Entry":
			rows = frappe.get_all(document_type, filters=filters, fields=["name", "party_type", "party"])
		elif document_type in ("Sales Invoice", "Purchase Invoice"):
			party_field = PARTY_FIELD[document_type]
			rows = frappe.get_all(document_type, filters=filters, fields=["name", f"{party_field} as party"])
			for row in rows:
				row.party_type = PARTY_TYPES[document_type]
		elif document_type == "Journal Entry":
			for name, party in get_journal_entry_parties(names).items():
				parties[(document_type, name)] = party
			continue
		else:
			continue
		for row in rows:
			parties[(document_type, row.name)] = (row.party_type, row.party)
	return parties


def describe_signals(signals):
	"""Why a document is suggested: one entry per signal, drawn as a hint with its description on hover."""
	reasons = []
	if signals.amount:
		exact = signals.amount == 1
		reasons.append(
			{
				"signal": "amount",
				"exact": exact,
				"description": _("Same amount") if exact else _("Close amount"),
			}
		)
	if signals.reference:
		exact = signals.reference >= YEAR_AND_COUNTER
		reasons.append(
			{
				"signal": "reference",
				"exact": exact,
				"description": _("Number in the label") if exact else _("Similar number in the label"),
			}
		)
	if signals.name:
		exact = signals.name == 1
		reasons.append(
			{
				"signal": "name",
				"exact": exact,
				"description": _("Name in the label") if exact else _("Contact in the label"),
			}
		)
	if signals.history:
		reasons.append(
			{
				"signal": "history",
				"exact": True,
				"description": _("Same account as past payments")
				if signals.same_account
				else _("Recognized from past payments"),
			}
		)
	if is_damped(signals.reference, signals.corrected):
		# Evidence against the party: shown so that a demoted lead does not look arbitrary
		reasons.append(
			{
				"signal": "corrected",
				"exact": False,
				"against": True,
				"description": _("You picked another party for similar lines"),
			}
		)
	if is_posted_after_payment(signals.reference, signals.days_after):
		reasons.append(
			{
				"signal": "date",
				"exact": False,
				"against": True,
				"description": _("Posted well after the payment"),
			}
		)
	elif signals.is_near:
		reasons.append({"signal": "date", "exact": True, "description": _("Posted near the payment")})
	return reasons
