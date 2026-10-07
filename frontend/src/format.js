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

// `8 juil. 26`: short enough to show a range beside each period of the picker
export function formatShortDate(value) {
	return new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "2-digit" }).format(
		new Date(value),
	);
}

export const DOCTYPE_ICONS = {
	"Sales Invoice": "lucide-file-text",
	"Purchase Invoice": "lucide-receipt",
	"Payment Entry": "lucide-banknote",
	"Journal Entry": "lucide-book-open",
	"Expense Claim": "lucide-wallet",
};

export function deskUrl(doctype, name) {
	return `/app/${doctype.toLowerCase().replaceAll(" ", "-")}/${encodeURIComponent(name)}`;
}
