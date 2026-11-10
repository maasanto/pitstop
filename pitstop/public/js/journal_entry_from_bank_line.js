// /pitstop opens /app/journal-entry/new?pitstop_line=<Bank Transaction>. The desk drops query keys that are not
// fields and rewrites the URL before this script runs, so the line is read from the URL the tab was opened with.
// It is meant for the form the tab opened on only: any other entry in that tab starts empty.
let pending_line = new URL(performance.getEntriesByType("navigation")[0].name).searchParams.get("pitstop_line");

frappe.ui.form.on("Journal Entry", {
	onload(frm) {
		const bank_transaction = pending_line;
		pending_line = null;
		const is_opening_form = frappe.route_history.every(
			([view, doctype, name]) => view === "Form" && doctype === "Journal Entry" && ["new", frm.doc.name].includes(name)
		);
		if (!frm.is_new() || !bank_transaction || !is_opening_form) return;
		frappe
			.xcall("pitstop.api.get_journal_entry_values", { bank_transaction })
			// frappe.xcall has already shown the server's message
			.catch(() => null)
			.then((values) => values && fill_from_line(frm, values))
			.catch((error) => {
				console.error(error);
				frappe.show_alert({
					message: __("The journal entry could not be filled from bank line {0}", [bank_transaction]),
					indicator: "red",
				});
			});
	},
});

async function fill_from_line(frm, { company, posting_date, multi_currency, bank_row, ...header }) {
	if (company !== frm.doc.company) await frm.set_value("company", company);
	// Before the bank row: its exchange rate is read on the posting date, and forced to 1 on a single-currency entry
	await frm.set_value({ posting_date, multi_currency });
	const row = (frm.doc.accounts || []).find((account) => !account.account) || frm.add_child("accounts");
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
