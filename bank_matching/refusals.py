"""Leads the user refused for a line, kept on the server.

A refusal follows the line to every browser and colleague. Once the line is reconciled with another party, it
also tells the matcher which party lines from that counterparty are not (see `ranking.get_corrections`).
"""

import frappe

from bank_matching.ranking import get_document_parties


def get_refused(line_names: list[str]) -> dict[str, list[str]]:
	refused = {}
	for row in frappe.get_all(
		"Bank Match Refusal",
		filters={"bank_transaction": ("in", line_names or [""])},
		fields=["bank_transaction", "proposal"],
		order_by="creation",
	):
		refused.setdefault(row.bank_transaction, []).append(row.proposal)
	return refused


def set_refused(bank_transaction: str, proposals: list[str]) -> None:
	"""Make the line's refusals exactly these proposals: the page sends the whole list on each change."""
	existing = {
		row.proposal: row.name
		for row in frappe.get_all(
			"Bank Match Refusal",
			filters={"bank_transaction": bank_transaction},
			fields=["name", "proposal"],
		)
	}
	for proposal, name in existing.items():
		if proposal not in proposals:
			frappe.delete_doc("Bank Match Refusal", name, ignore_permissions=True)
	for proposal in dict.fromkeys(proposals):
		if proposal in existing:
			continue
		party_type, party = proposal_party(proposal) or (None, None)
		frappe.get_doc(
			{
				"doctype": "Bank Match Refusal",
				"bank_transaction": bank_transaction,
				"proposal": proposal,
				"party_type": party_type,
				"party": party,
			}
		).insert(ignore_permissions=True)


def proposal_party(proposal: str) -> tuple[str, str] | None:
	"""The one party a refused proposal points at; none for a rule, or a settlement of several parties."""
	kind, _, names = proposal.partition(":")
	if kind == "rule":
		return None
	if kind == "settlement":
		links = [
			frappe._dict(payment_document="Payment Entry", payment_entry=name) for name in names.split(",")
		]
	else:
		links = [frappe._dict(payment_document=kind, payment_entry=names)]
	parties = set(get_document_parties(links).values())
	return parties.pop() if len(parties) == 1 else None


def delete_line_refusals(bank_transaction, method=None) -> None:
	frappe.db.delete("Bank Match Refusal", {"bank_transaction": bank_transaction.name})
