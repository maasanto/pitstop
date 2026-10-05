const locale = () => window.lang || "en";

export function formatMoney(amount, currency) {
	return new Intl.NumberFormat(locale(), {
		style: "currency",
		currency: currency || window.default_currency || "EUR",
	}).format(amount || 0);
}

export function formatDate(value) {
	return value ? new Intl.DateTimeFormat(locale()).format(new Date(value)) : "";
}

export const DOCTYPE_ICONS = {
	"Sales Invoice": "lucide-file-text",
	"Purchase Invoice": "lucide-receipt",
	"Payment Entry": "lucide-banknote",
	"Journal Entry": "lucide-book-open",
	"Expense Claim": "lucide-wallet",
};

const SIGNAL_ICONS = {
	reference: "lucide-hash",
	name: "lucide-user",
	history: "lucide-history",
	batch: "lucide-layers",
};

export function signalIcon(reason) {
	if (reason.signal === "amount") {
		return reason.exact ? "lucide-equal" : "lucide-equal-approximately";
	}
	return SIGNAL_ICONS[reason.signal];
}

export function deskUrl(doctype, name) {
	return `/app/${doctype.toLowerCase().replaceAll(" ", "-")}/${encodeURIComponent(name)}`;
}
