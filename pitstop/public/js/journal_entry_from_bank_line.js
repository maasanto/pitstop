// /pitstop opens /app/journal-entry/new?pitstop_line=<Bank Transaction>. The desk drops query keys that are not
// fields and rewrites the URL before this script runs, so the line is read from the URL the tab was opened with.
// Read once: a later new entry in the same tab starts empty.
let pending_line = new URL(performance.getEntriesByType("navigation")[0].name).searchParams.get("pitstop_line");

frappe.ui.form.on("Journal Entry", {
	onload(frm) {
		const bank_transaction = pending_line;
		pending_line = null;
		if (!frm.is_new() || !bank_transaction) return;
		fill_from_line(frm, bank_transaction).catch((error) => {
			console.error(error);
			frappe.show_alert({
				message: __("The journal entry could not be filled from bank line {0}", [bank_transaction]),
				indicator: "red",
			});
		});
	},
});

async function fill_from_line(frm, bank_transaction) {
	const { company, posting_date, multi_currency, bank_row, ...header } = await frappe.xcall(
		"pitstop.api.get_journal_entry_values",
		{ bank_transaction }
	);
	if (company !== frm.doc.company) await frm.set_value("company", company);
	// Before the bank row: its exchange rate is read on the posting date, and forced to 1 on a single-currency entry
	await frm.set_value({ posting_date, multi_currency });
	const row = frm.doc.accounts.find((account) => !account.account) || frm.add_child("accounts");
	await frappe.model.set_value(row.doctype, row.name, bank_row);
	// The account's details come back with the first Bank Account on that ledger account: the line's own one wins
	await frappe.after_ajax();
	await frappe.model.set_value(row.doctype, row.name, "bank_account", bank_row.bank_account);
	// After the bank row: on an entry without accounts, the voucher type adds the company's default bank
	await frm.set_value(header);
	// The company picked the accounting journal before the entry was a Bank Entry
	erpnext.set_accounting_journal(frm);
	frm.refresh_field("accounts");
}
