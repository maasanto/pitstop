// Lifted from erpnext's /banking date filter (banking/src/components/features/BankReconciliation/
// BankRecDateFilter.tsx), with chrono's parser for the user's language tried before the English one.
import { en, fr } from "chrono-node";
import { dayjs } from "frappe-ui";

const ISO = "YYYY-MM-DD";

const FRENCH_MONTHS = [
	"janvier",
	"f[ée]vrier",
	"mars",
	"avril",
	"mai",
	"juin",
	"juillet",
	"ao[ûu]t",
	"septembre",
	"octobre",
	"novembre",
	"d[ée]cembre",
];
const FRENCH_UNITS = { jour: "day", semaine: "week", mois: "month", an: "year", année: "year" };
// chrono's French parser reads "1er septembre" but neither a bare month ("mai 2025", "septembre") nor
// "3 dernières semaines", the wording of the period list itself
const french = fr.casual.clone();
// First, so that "les 2 derniers mois" is not taken by chrono's own "dernier mois" (last month)
french.parsers.unshift(
	{
		pattern: () => new RegExp(`\\b(${FRENCH_MONTHS.join("|")})(?:\\s+(\\d{4}))?\\b`, "i"),
		extract: (context, match) => {
			const month = FRENCH_MONTHS.findIndex((name) => new RegExp(`^${name}$`, "i").test(match[1])) + 1;
			return match[2] ? { month, year: Number(match[2]) } : { month };
		},
	},
	{
		pattern: () => /(?:les\s+)?(\d+)\s+derni[eè]re?s?\s+(jour|semaine|mois|an|année)s?/i,
		extract: (context, match) => {
			const start = dayjs().subtract(Number(match[1]), FRENCH_UNITS[match[2].toLowerCase()]);
			return { day: start.date(), month: start.month() + 1, year: start.year() };
		},
	},
);

// Only the locales Dokos users type in: importing chrono whole bundles every language it knows
const LOCALES = { en, fr: french };

const REFERENTIAL_KEYWORDS = [
	"last",
	"this",
	"next",
	"previous",
	"since",
	"ago",
	"il y a",
	"dernier",
	"dernière",
	"ce ",
	"cette",
	"précédent",
	"depuis",
];

const knownValuesOf = (components) => components?.knownValues ?? {};

/**
 * How far back a parsed date must move to land in the past. Reconciliation only ever looks
 * backwards, so an ambiguous input that chrono resolves into the future - "December" typed in
 * September, or a bare weekday like "Friday" - is pulled to its most recent past occurrence.
 * An explicitly stated year is respected; a range that is still future gets discarded later.
 *
 * This returns a shift rather than a date so that a range can be moved as a single unit -
 * shifting its start and end independently would distort or invert it.
 */
function pastShift(date, knownValues) {
	const today = dayjs();
	let candidate = dayjs(date);

	if (!candidate.isAfter(today, "date") || knownValues.year !== undefined) {
		return { amount: 0, unit: "year" };
	}

	// A bare weekday repeats weekly, everything else (month/day) repeats yearly.
	const unit = knownValues.weekday !== undefined && knownValues.day === undefined ? "day" : "year";
	const step = unit === "day" ? 7 : 1;
	let amount = 0;

	for (let i = 0; i < 200 && candidate.isAfter(today, "date"); i++) {
		candidate = candidate.subtract(step, unit);
		amount += step;
	}

	return { amount, unit };
}

function parseFirst(value) {
	const locales = [LOCALES[window.lang], en].filter(Boolean);
	for (const locale of locales) {
		const results = locale.parse(value, undefined, { forwardDate: false });
		if (results?.length) return results[0];
	}
	return undefined;
}

/**
 * Parse free text into a past date range, or return undefined when it can't be parsed or
 * resolves entirely into the future.
 */
export function parseDateRange(value) {
	if (!value.trim()) return undefined;

	const result = parseFirst(value);
	if (!result) return undefined;

	const startKnownValues = knownValuesOf(result.start);

	// Anchor the shift on the start and apply it to both ends, so an explicit range like
	// "1st Sept to 30th Sept" keeps its shape instead of having only its end rolled back.
	const shift = pastShift(result.start.date(), startKnownValues);
	const startDate = dayjs(result.start.date()).subtract(shift.amount, shift.unit).toDate();
	const endDate = result.end ? dayjs(result.end.date()).subtract(shift.amount, shift.unit).toDate() : undefined;

	const today = new Date();
	let range;

	if (endDate) {
		const endKnownValues = knownValuesOf(result.end);
		// chrono ends "Apr 2025 to Jun 2025" on the 1st of June, but the user means all of it.
		const rangeEnd = endKnownValues.month && !endKnownValues.day ? dayjs(endDate).endOf("month").toDate() : endDate;
		range = { fromDate: startDate, toDate: rangeEnd };
	} else if (startKnownValues.month && !startKnownValues.day) {
		// The user only wants a specific month like "May 2025" - span the whole month
		range = {
			fromDate: dayjs(startDate).startOf("month").toDate(),
			toDate: dayjs(startDate).endOf("month").toDate(),
		};
	} else if (
		startKnownValues.month &&
		startKnownValues.day &&
		!REFERENTIAL_KEYWORDS.some((keyword) => value.toLowerCase().includes(keyword))
	) {
		// If month and day is known, then we should not assume that the user wants to get everything until today
		range = { fromDate: startDate, toDate: startDate };
	} else {
		range = { fromDate: startDate, toDate: today };
	}

	// A range that hasn't started yet is never useful for reconciliation. A range that merely
	// ends in the future is kept as typed, the same way "This Month" spans the whole month.
	if (dayjs(range.fromDate).isAfter(today, "date")) return undefined;

	if (dayjs(range.toDate).isBefore(range.fromDate, "date")) {
		range = { fromDate: range.toDate, toDate: range.fromDate };
	}

	return { from: dayjs(range.fromDate).format(ISO), to: dayjs(range.toDate).format(ISO) };
}
