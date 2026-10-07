<script setup>
import { Button, DateRangePicker, Popover, TextInput, call, dayjs } from "frappe-ui";
import { computed, ref, watch } from "vue";
import { parseDateRange } from "../dateRange";
import { formatDate, formatShortDate } from "../format";
import { __ } from "../translation";

// The periods of /banking's date filter, with rolling windows first: a reconciliation catches up on recent weeks
const period = defineModel({ type: Array, required: true });
const props = defineProps({ company: { type: String, default: null } });

const ISO = "YYYY-MM-DD";
const ROLLING_DAYS = [30, 60, 90];
// Fiscal years before the current one whose quarters and year stay searchable
const PREVIOUS_FISCAL_YEARS = 2;

const fiscalYear = ref(null);
watch(
	() => props.company,
	async (company) => {
		fiscalYear.value = company
			? await call("erpnext.accounts.utils.get_fiscal_year", {
					date: dayjs().format(ISO),
					company,
					as_dict: true,
					raise_on_missing: false,
					verbose: 0,
				})
			: null;
	},
	{ immediate: true },
);

// The English name stays searchable beside the translated one, as on /banking: "Q1" or "last month" find
// "T1 2026" and "Le mois dernier". A period that is not `listed` only shows once the search matches it.
const option = (group, english, label, from, to, { keywords = [], listed = true } = {}) => ({
	group,
	english,
	label,
	keywords,
	listed,
	from: from.format(ISO),
	to: to.format(ISO),
});

// `2026`, or `2025-2026` for a fiscal year straddling two calendar years
const yearLabel = (start, end) => (start.year() === end.year() ? `${start.year()}` : `${start.year()}-${end.year()}`);

// Fiscal years keep their month and day year on year: the earlier ones are derived, not fetched
function fiscalOptions() {
	if (!fiscalYear.value) return [];
	const currentStart = dayjs(fiscalYear.value.year_start_date);
	const currentEnd = dayjs(fiscalYear.value.year_end_date);
	const recentYears = [
		["This fiscal year", __("This fiscal year")],
		["Last fiscal year", __("Last fiscal year")],
	];
	return Array.from({ length: PREVIOUS_FISCAL_YEARS + 1 }, (_, yearsAgo) => {
		const start = currentStart.subtract(yearsAgo, "year");
		const end = currentEnd.subtract(yearsAgo, "year");
		const year = yearsAgo ? yearLabel(start, end) : fiscalYear.value.name;
		const quarters = [0, 1, 2, 3]
			.filter((index) => !start.add(3 * index, "month").isAfter(end))
			.map((index) => {
				const quarterEnd = start.add(3 * (index + 1), "month").subtract(1, "day");
				return option(
					"fiscal",
					`Q${index + 1} ${year}`,
					__("Q{0} {1}", [index + 1, year]),
					start.add(3 * index, "month"),
					quarterEnd.isAfter(end) ? end : quarterEnd,
					{ keywords: ["quarter"], listed: !yearsAgo },
				);
			});
		const [english, label] = recentYears[yearsAgo] || [`FY ${year}`, __("FY {0}", [year])];
		const fiscalYearOption = option("fiscal", english, label, start, end, {
			keywords: ["fiscal year", year],
			listed: yearsAgo < recentYears.length,
		});
		return [...quarters, fiscalYearOption];
	}).flat();
}

const options = computed(() => {
	const today = dayjs().startOf("day");
	const monday = today.subtract((today.day() + 6) % 7, "day");
	const quarterStart = today.subtract(today.month() % 3, "month").startOf("month");
	const lastMonth = today.subtract(1, "month");
	const lastYear = today.subtract(1, "year");
	const all = [
		...ROLLING_DAYS.map((days) =>
			option("rolling", `Last ${days} days`, __("Last {0} days", [days]), today.subtract(days - 1, "day"), today),
		),
		option("month", "This month", __("This month"), today.startOf("month"), today.endOf("month")),
		option("month", "Last month", __("Last month"), lastMonth.startOf("month"), lastMonth.endOf("month")),
		...fiscalOptions(),
		option("other", "This week", __("This week"), monday, monday.add(6, "day")),
		option("other", "Last week", __("Last week"), monday.subtract(7, "day"), monday.subtract(1, "day")),
		option("other", "This quarter", __("This quarter"), quarterStart, quarterStart.add(2, "month").endOf("month")),
		option("other", "Last quarter", __("Last quarter"), quarterStart.subtract(3, "month"), quarterStart.subtract(1, "day")),
		option("other", "This year", __("This year"), today.startOf("year"), today.endOf("year")),
		option("other", "Last year", __("Last year"), lastYear.startOf("year"), lastYear.endOf("year")),
	];
	// Reconciliation only looks back, so a period that has not started is never useful. The listed periods
	// come first, so that the one naming the current range is a listed one when several do.
	const started = all.filter((candidate) => candidate.from <= today.format(ISO));
	return [...started.filter((candidate) => candidate.listed), ...started.filter((candidate) => !candidate.listed)];
});

const isCurrent = (candidate) => candidate.from === period.value[0] && candidate.to === period.value[1];
const current = computed(() => options.value.find(isCurrent));

const isOpen = ref(false);
const query = ref("");
const highlighted = ref(0);
const matching = computed(() => {
	const tokens = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
	const found = options.value.filter((candidate) => {
		if (!tokens.length) return candidate.listed;
		const text = [candidate.label, candidate.english, ...candidate.keywords, candidate.from, candidate.to]
			.join(" ")
			.toLowerCase();
		return tokens.every((token) => text.includes(token));
	});
	// A calendar fiscal year repeats the calendar quarters and year: keep the first period of each range
	const seen = new Set();
	return found.filter((candidate) => {
		const range = `${candidate.from}|${candidate.to}`;
		return !seen.has(range) && seen.add(range);
	});
});
// What the user typed, read as dates ("May 2025", "since 3 weeks"), unless a period already covers it
const typed = computed(() => {
	const range = parseDateRange(query.value);
	const isListed = matching.value.some((candidate) => candidate.from === range?.from && candidate.to === range?.to);
	return range && !isListed ? { group: "typed", label: query.value.trim(), ...range } : null;
});
const shown = computed(() => (typed.value ? [typed.value, ...matching.value] : matching.value));
watch(query, () => (highlighted.value = 0));
watch(isOpen, (open) => {
	query.value = "";
	if (open) highlighted.value = Math.max(shown.value.findIndex(isCurrent), 0);
});

function pick(candidate) {
	period.value = [candidate.from, candidate.to];
	isOpen.value = false;
}

function onSearchKeydown(event) {
	const moves = { ArrowDown: 1, ArrowUp: -1 };
	if (moves[event.key]) {
		event.preventDefault();
		highlighted.value = Math.min(Math.max(highlighted.value + moves[event.key], 0), shown.value.length - 1);
	} else if (event.key === "Enter" && shown.value[highlighted.value]) {
		event.preventDefault();
		pick(shown.value[highlighted.value]);
	}
}
</script>

<template>
	<div class="flex items-center">
		<Popover v-model:open="isOpen" align="start">
			<template #trigger>
				<Button
					variant="subtle"
					class="rounded-r-none"
					icon-left="lucide-calendar-range"
					icon-right="lucide-chevron-down"
					:label="current?.label || __('Custom period')"
				/>
			</template>
			<div class="w-[23rem] p-1.5">
				<TextInput
					v-model="query"
					autofocus
					:placeholder="__('e.g. Last 3 weeks, Q1, May 2025')"
					@keydown="onSearchKeydown"
				>
					<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
				</TextInput>
				<ul class="mt-1.5 max-h-80 overflow-y-auto" role="listbox" :aria-label="__('Periods')">
					<template v-for="(candidate, index) in shown" :key="`${candidate.group}:${candidate.label}`">
						<li
							v-if="candidate.group === 'typed'"
							role="presentation"
							class="px-2.5 pb-1 pt-1.5 text-xs text-ink-gray-5"
						>
							{{ __("Matched date") }}
						</li>
						<li
							v-else-if="index && candidate.group !== shown[index - 1].group"
							role="separator"
							class="mx-2.5 my-1 border-t border-outline-gray-1"
						/>
						<li
							role="option"
							:aria-selected="isCurrent(candidate)"
							class="flex cursor-pointer items-center justify-between gap-4 rounded px-2.5 py-2 text-base"
							:class="index === highlighted ? 'bg-surface-gray-3' : ''"
							@mouseenter="highlighted = index"
							@click="pick(candidate)"
						>
							<span class="flex min-w-0 items-center gap-2 text-ink-gray-8">
								<span
									class="size-4 shrink-0"
									:class="{
										'lucide-check text-ink-gray-9': candidate.group !== 'typed' && isCurrent(candidate),
										'lucide-text-cursor-input text-ink-gray-5': candidate.group === 'typed',
									}"
									aria-hidden="true"
								/>
								<span class="truncate">{{ candidate.label }}</span>
							</span>
							<span class="flex items-center gap-1 whitespace-nowrap text-sm tabular-nums text-ink-gray-5">
								{{ formatShortDate(candidate.from) }}
								<template v-if="candidate.to !== candidate.from">
									<span class="lucide-arrow-right size-3" aria-hidden="true" />
									{{ formatShortDate(candidate.to) }}
								</template>
							</span>
						</li>
					</template>
					<li v-if="!shown.length" class="px-2.5 py-2 text-sm text-ink-gray-5">
						{{ __("No period matches: pick the dates on the calendar") }}
					</li>
				</ul>
			</div>
		</Popover>
		<DateRangePicker v-model="period" dual-pane :clearable="false">
			<template #trigger="{ togglePopover }">
				<Button
					variant="subtle"
					class="rounded-l-none border-l border-outline-gray-2 tabular-nums"
					:label="`${formatDate(period[0])} – ${formatDate(period[1])}`"
					@click="togglePopover"
				/>
			</template>
		</DateRangePicker>
	</div>
</template>
