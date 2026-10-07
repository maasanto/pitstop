// From an open invoice or payment, the bank lines it may have been paid by, scored as on /pitstop.
// The file is loaded once per doctype it is hooked on: register the handlers a single time.
if (!frappe.pitstop_find_line) {
	frappe.pitstop_find_line = true;
	["Sales Invoice", "Purchase Invoice", "Payment Entry"].forEach((doctype) =>
		frappe.ui.form.on(doctype, { refresh: add_find_bank_line_button }),
	);
}

const CONFIDENCE = {
	high: { label: () => __("High", null, "Confidence"), color: "green" },
	medium: { label: () => __("Medium", null, "Confidence"), color: "orange" },
	low: { label: () => __("Low", null, "Confidence"), color: "gray" },
};

function add_find_bank_line_button(frm) {
	const is_open =
		frm.doc.doctype === "Payment Entry" ? !frm.doc.clearance_date : flt(frm.doc.outstanding_amount) !== 0;
	if (frm.doc.docstatus !== 1 || !is_open) return;
	frm.add_custom_button(__("Find the bank line"), () => show_bank_lines(frm));
}

function show_bank_lines(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Bank lines for {0}", [frm.doc.name]),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "lines" }],
	});
	const wrapper = dialog.fields_dict.lines.$wrapper;
	wrapper.html(`<p class="text-muted">${__("Looking for matching bank lines…")}</p>`);
	dialog.show();

	frappe
		.call("pitstop.lookup.get_lines_for_document", { doctype: frm.doc.doctype, name: frm.doc.name })
		.then(({ message }) => {
			wrapper.html(render_lines(message.lines, frm));
			wrapper.on("click", "[data-bank-transaction]", (event) =>
				reconcile(frm, dialog, event.currentTarget.dataset.bankTransaction),
			);
		});
}

function render_lines(lines, frm) {
	const query = new URLSearchParams({ doctype: frm.doc.doctype, name: frm.doc.name });
	const page_link = `<p class="mt-3"><a href="/pitstop?${query}" target="_blank">${__(
		"Open the reconciliation page",
	)}</a></p>`;
	if (!lines.length) {
		return `<p class="text-muted">${__("No open bank line matches this document.")}</p>${page_link}`;
	}
	return `<div class="list-group">${lines.map(render_line).join("")}</div>${page_link}`;
}

function render_line({ line, proposal }) {
	const confidence = CONFIDENCE[proposal.level];
	const score = __("Score: {0}", [`${Math.round(proposal.score * 100)} %`]);
	const reasons = proposal.documents[0].reasons.map((reason) => reason.description).join(" · ");
	return `
		<div class="list-group-item d-flex align-items-center" style="gap: var(--padding-md)">
			<div style="flex: 1; min-width: 0">
				<div class="ellipsis" title="${frappe.utils.escape_html(line.description || "")}">
					${frappe.utils.escape_html(line.description || line.name)}
				</div>
				<div class="text-muted small">
					${frappe.datetime.str_to_user(line.date)}${reasons ? ` · ${frappe.utils.escape_html(reasons)}` : ""}
				</div>
			</div>
			<span class="indicator-pill ${confidence.color}" title="${score}">${confidence.label()}</span>
			<b class="text-nowrap">${format_currency(line.amount, line.currency)}</b>
			<button class="btn btn-sm btn-primary" data-bank-transaction="${frappe.utils.escape_html(line.name)}">
				${__("Reconcile")}
			</button>
		</div>`;
}

function reconcile(frm, dialog, bank_transaction) {
	frappe
		.call({
			method: "pitstop.lookup.reconcile_document",
			args: { doctype: frm.doc.doctype, name: frm.doc.name, bank_transaction },
			freeze: true,
		})
		.then(() => {
			dialog.hide();
			frappe.show_alert({ message: __("Reconciled with {0}", [bank_transaction]), indicator: "green" });
			frm.reload_doc();
		});
}
