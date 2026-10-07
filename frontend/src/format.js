import { dayjs } from "frappe-ui";

const locale = () => window.lang || "en";

export function formatMoney(amount, currency) {
	return new Intl.NumberFormat(locale(), {
		style: "currency",
		currency: currency || window.default_currency || "EUR",
	}).format(amount || 0);
}

// The system's date format, as the desk shows dates: `dd-mm-yyyy` reads as dayjs' `DD-MM-YYYY`
export function formatDate(value) {
	if (!value) return "";
	return window.date_format
		? dayjs(value).format(window.date_format.toUpperCase())
		: new Intl.DateTimeFormat(locale()).format(dayjs(value).toDate());
}

// `8 juil.`, short enough to show a range beside each period of the picker; the year only when it is not this one
export function formatShortDate(value) {
	const date = dayjs(value);
	const year = date.year() === dayjs().year() ? {} : { year: "numeric" };
	return new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", ...year }).format(date.toDate());
}

export function formatPercent(ratio) {
	return new Intl.NumberFormat(locale(), { style: "percent" }).format(ratio);
}

// Bank imports can carry HTML such as `<br>`: show it as plain text, line breaks kept, never as markup
export function descriptionText(description) {
	const html = (description || "").replace(/<br\s*\/?>|<\/(p|div|li)>/gi, "\n");
	return new DOMParser().parseFromString(html, "text/html").body.textContent.trim();
}

export const DOCTYPE_ICONS = {
	"Sales Invoice": "lucide-file-text",
	"Purchase Invoice": "lucide-receipt",
	"Payment Entry": "lucide-banknote",
	"Journal Entry": "lucide-book-open",
	"Expense Claim": "lucide-wallet",
	"Payment Order": "lucide-send",
	"Sepa Direct Debit": "lucide-hand-coins",
};

export function deskUrl(doctype, name) {
	return `/app/${doctype.toLowerCase().replaceAll(" ", "-")}/${encodeURIComponent(name)}`;
}
