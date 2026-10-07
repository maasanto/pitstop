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

// Green, red and amber already mean approved, outgoing and gap on the cards: types take the other hues.
// Class names stay literal so Tailwind keeps them.
export const DOCUMENT_TYPES = {
	"Sales Invoice": { icon: "lucide-file-text", tint: "bg-surface-blue-2 text-ink-blue-7" },
	"Purchase Invoice": { icon: "lucide-receipt", tint: "bg-surface-orange-2 text-ink-orange-7" },
	"Payment Entry": { icon: "lucide-banknote", tint: "bg-surface-teal-2 text-ink-teal-7" },
	"Journal Entry": { icon: "lucide-book-open", tint: "bg-surface-violet-2 text-ink-violet-7" },
	"Expense Claim": { icon: "lucide-wallet", tint: "bg-surface-pink-2 text-ink-pink-7" },
	"Payment Order": { icon: "lucide-send", tint: "bg-surface-yellow-2 text-ink-yellow-7" },
	"Sepa Direct Debit": { icon: "lucide-hand-coins", tint: "bg-surface-cyan-2 text-ink-cyan-7" },
};

export function deskUrl(doctype, name) {
	return `/app/${doctype.toLowerCase().replaceAll(" ", "-")}/${encodeURIComponent(name)}`;
}
