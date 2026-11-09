// /pitstop's "Create a journal entry" leaves the bank line here and opens a new entry.
// A URL cannot carry it: the desk drops the no-copy fields (date, reference, remark) and fills no table row.
const PENDING_LINE_KEY = "pitstop:journal-entry-line";

frappe.ui.form.on("Journal Entry", {
	onload(frm) {
		const bank_transaction = localStorage.getItem(PENDING_LINE_KEY);
		if (!frm.is_new() || !bank_transaction) return;
		localStorage.removeItem(PENDING_LINE_KEY);
		frappe
			.call("pitstop.api.get_journal_entry_values", { bank_transaction })
			.then(({ message }) => fill_from_line(frm, message));
	},
});

async function fill_from_line(frm, { company, bank_row, ...values }) {
	if (company !== frm.doc.company) await frm.set_value("company", company);
	const row = frm.doc.accounts.find((account) => !account.account) || frm.add_child("accounts");
	await frappe.model.set_value(row.doctype, row.name, bank_row);
	// After the bank row: on an entry without accounts, the voucher type adds the company's default bank
	await frm.set_value(values);
	frm.refresh_field("accounts");
}
