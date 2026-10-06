<script setup>
import { Button, Tooltip } from "frappe-ui";
import { computed } from "vue";
import { DOCTYPE_ICONS, deskUrl, formatDate, formatMoney } from "../format";
import { __ } from "../translation";
import MatchHint from "./MatchHint.vue";

const props = defineProps({
	document: { type: Object, required: true },
	currency: { type: String, default: null },
	lineAmount: { type: Number, default: null },
	// One line per document, for the receipts of a settlement
	compact: { type: Boolean, default: false },
});
defineEmits(["preview"]);

const gap = computed(() =>
	props.lineAmount === null
		? 0
		: Math.round((Math.abs(props.lineAmount) - props.document.amount) * 100) / 100,
);
const party = computed(() => props.document.party_name || props.document.party);
// Who the money is from or to is what the user recognizes first; a journal entry has only its reference
const title = computed(() => party.value || props.document.reference || __(props.document.doctype));
const details = computed(() =>
	[
		party.value && props.document.reference,
		props.document.due_date
			? __("due {0}", [formatDate(props.document.due_date)])
			: formatDate(props.document.posting_date),
	]
		.filter(Boolean)
		.join(" · "),
);
const reasonsAbout = (...signals) =>
	props.document.reasons.filter((reason) => signals.includes(reason.signal));
</script>

<template>
	<div v-if="compact" class="flex items-center gap-1.5 py-1 text-sm">
		<a
			:href="deskUrl(document.doctype, document.name)"
			target="_blank"
			class="shrink-0 text-ink-gray-7 hover:underline"
			@click.stop
			>{{ document.name }}</a
		>
		<span class="truncate text-ink-gray-5">· {{ party }} · {{ formatDate(document.posting_date) }}</span>
		<span class="ml-auto shrink-0 tabular-nums text-ink-gray-7">{{ formatMoney(document.amount, currency) }}</span>
		<Button
			variant="ghost"
			size="sm"
			icon="lucide-eye"
			:label="__('Preview')"
			@click.stop="$emit('preview', document)"
		/>
	</div>
	<div v-else class="min-w-0">
		<div class="flex items-center gap-1.5">
			<span class="truncate text-base-medium text-ink-gray-9">{{ title }}</span>
			<MatchHint v-if="party" :reasons="reasonsAbout('name', 'history')" :missing="__('Name not in the label')" />
			<span class="ml-auto shrink-0 pl-2 text-base-semibold tabular-nums text-ink-gray-9">
				{{ formatMoney(document.amount, currency) }}
			</span>
			<MatchHint v-if="lineAmount !== null" :reasons="reasonsAbout('amount')" :missing="__('Different amount')" />
		</div>
		<div class="mt-1.5 flex items-center gap-1.5 text-sm text-ink-gray-5">
			<Tooltip :text="__(document.doctype)">
				<span :class="DOCTYPE_ICONS[document.doctype]" class="size-3.5 shrink-0" :aria-label="__(document.doctype)" />
			</Tooltip>
			<a
				:href="deskUrl(document.doctype, document.name)"
				target="_blank"
				class="shrink-0 text-ink-gray-6 hover:text-ink-gray-8 hover:underline"
				@click.stop
				>{{ document.name }}</a
			>
			<MatchHint :reasons="reasonsAbout('reference')" :missing="__('Number not in the label')" />
			<span v-if="details" class="truncate">· {{ details }}</span>
			<slot name="note" />
			<span
				v-if="gap"
				class="ml-auto shrink-0 rounded-3 bg-surface-amber-2 px-1 tabular-nums text-ink-amber-7"
				:title="__('Gap between the bank line and the document')"
			>
				{{ gap > 0 ? "+" : "−" }}{{ formatMoney(Math.abs(gap), currency) }}
			</span>
		</div>
	</div>
</template>
