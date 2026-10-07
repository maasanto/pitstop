<script setup>
import { Button, DateRangePicker, Popover, TextInput, call, dayjs } from "frappe-ui";
import { computed, ref, watch } from "vue";
import { formatDate, formatShortDate } from "../format";
import { __ } from "../translation";

// The periods of /banking's date filter, with rolling windows first: a reconciliation catches up on recent weeks
const period = defineModel({ type: Array, required: true });
const props = defineProps({ company: { type: String, default: null } });

const ISO = "YYYY-MM-DD";
const ROLLING_DAYS = [30, 60, 90];

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

const option = (group, label, from, to) => ({ group, label, from: from.format(ISO), to: to.format(ISO) });

function fiscalOptions() {
	if (!fiscalYear.value) return [];
	const start = dayjs(fiscalYear.value.year_start_date);
	const end = dayjs(fiscalYear.value.year_end_date);
	const quarters = [0, 1, 2, 3].map((index) => {
		const quarterEnd = start.add(3 * (index + 1), "month").subtract(1, "day");
		return option(
			"fiscal",
			__("Q{0} {1}", [index + 1, fiscalYear.value.name]),
			start.add(3 * index, "month"),
			quarterEnd.isAfter(end) ? end : quarterEnd,
		);
	});
	return [
		...quarters,
		option("fiscal", __("This fiscal year"), start, end),
		option("fiscal", __("Last fiscal year"), start.subtract(1, "year"), end.subtract(1, "year")),
	];
}

const options = computed(() => {
	const today = dayjs().startOf("day");
	const monday = today.subtract((today.day() + 6) % 7, "day");
	const quarterStart = today.subtract(today.month() % 3, "month").startOf("month");
	const lastMonth = today.subtract(1, "month");
	const all = [
		...ROLLING_DAYS.map((days) =>
			option("rolling", __("Last {0} days", [days]), today.subtract(days - 1, "day"), today),
		),
		option("month", __("This month"), today.startOf("month"), today.endOf("month")),
		option("month", __("Last month"), lastMonth.startOf("month"), lastMonth.endOf("month")),
		...fiscalOptions(),
		option("other", __("This week"), monday, monday.add(6, "day")),
		option("other", __("Last week"), monday.subtract(7, "day"), monday.subtract(1, "day")),
		option("other", __("This quarter"), quarterStart, quarterStart.add(2, "month").endOf("month")),
		option("other", __("Last quarter"), quarterStart.subtract(3, "month"), quarterStart.subtract(1, "day")),
		option("other", __("This year"), today.startOf("year"), today.endOf("year")),
		option("other", __("Last year"), today.subtract(1, "year").startOf("year"), today.subtract(1, "year").endOf("year")),
	];
	// A calendar fiscal year repeats the calendar quarters and year: keep the first of each range.
	// Reconciliation only looks back, so a period that has not started is never useful.
	const seen = new Set();
	return all.filter((candidate) => {
		const range = `${candidate.from}|${candidate.to}`;
		if (seen.has(range) || candidate.from > today.format(ISO)) return false;
		seen.add(range);
		return true;
	});
});

const current = computed(() =>
	options.value.find((candidate) => candidate.from === period.value[0] && candidate.to === period.value[1]),
);

const isOpen = ref(false);
const query = ref("");
const highlighted = ref(0);
const shown = computed(() => {
	const tokens = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
	return options.value.filter((candidate) => {
		const text = [candidate.label, candidate.from, candidate.to].join(" ").toLowerCase();
		return tokens.every((token) => text.includes(token));
	});
});
watch(query, () => (highlighted.value = 0));
watch(isOpen, (open) => {
	query.value = "";
	if (open) highlighted.value = Math.max(shown.value.indexOf(current.value), 0);
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
					:placeholder="__('Search a period, e.g. Q1 or 2025')"
					@keydown="onSearchKeydown"
				>
					<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
				</TextInput>
				<ul class="mt-1.5 max-h-80 overflow-y-auto" role="listbox" :aria-label="__('Periods')">
					<template v-for="(candidate, index) in shown" :key="candidate.label">
						<li
							v-if="index && candidate.group !== shown[index - 1].group"
							role="separator"
							class="mx-2.5 my-1 border-t border-outline-gray-1"
						/>
						<li
							role="option"
							:aria-selected="candidate === current"
							class="flex cursor-pointer items-center justify-between gap-4 rounded px-2.5 py-2 text-base"
							:class="index === highlighted ? 'bg-surface-gray-3' : ''"
							@mouseenter="highlighted = index"
							@click="pick(candidate)"
						>
							<span class="flex items-center gap-2 text-ink-gray-8">
								<span
									class="size-4 shrink-0"
									:class="candidate === current ? 'lucide-check text-ink-gray-9' : ''"
									aria-hidden="true"
								/>
								{{ candidate.label }}
							</span>
							<span class="flex items-center gap-1 whitespace-nowrap text-sm tabular-nums text-ink-gray-5">
								{{ formatShortDate(candidate.from) }}
								<span class="lucide-arrow-right size-3" aria-hidden="true" />
								{{ formatShortDate(candidate.to) }}
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
