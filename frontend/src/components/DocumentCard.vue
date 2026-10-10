<script setup>
import { Button } from "frappe-ui";
import { computed } from "vue";
import { deskUrl, formatMoney } from "../format";
import { __ } from "../translation";
import DateLabel from "./DateLabel.vue";
import DocumentTypeIcon from "./DocumentTypeIcon.vue";
import MatchHint from "./MatchHint.vue";

const props = defineProps({
	document: { type: Object, required: true },
	currency: { type: String, default: null },
	lineAmount: { type: Number, default: null },
	// One line per document, for the receipts of a settlement
	compact: { type: Boolean, default: false },
});
defineEmits(["preview"]);

// A gap only helps when the amounts are close; next to an unrelated amount it is noise
const gap = computed(() =>
	props.lineAmount === null || !reasonsAbout("amount").length
		? 0
		: Math.round((Math.abs(props.lineAmount) - props.document.amount) * 100) / 100,
);
const party = computed(() => props.document.party_name || props.document.party);
// Who the money is from or to is what the user recognizes first; a journal entry has only its reference
const title = computed(() => party.value || props.document.reference || __(props.document.doctype));
// Without a party the reference is already the title
const reference = computed(() => party.value && props.document.reference);
const reasonsAbout = (...signals) =>
	props.document.reasons.filter((reason) => signals.includes(reason.signal));
</script>

<template>
	<div v-if="compact" class="flex items-center gap-1.5 py-2 text-sm">
		<DocumentTypeIcon :doctype="document.doctype" class="mr-1" />
		<a
			:href="deskUrl(document.doctype, document.name)"
			target="_blank"
			class="shrink-0 text-ink-gray-7 hover:underline"
			@click.stop
			>{{ document.name }}</a
		>
		<DateLabel :date="document.posting_date" />
		<span class="truncate text-ink-gray-5">· {{ party }}</span>
		<Button
			variant="ghost"
			size="sm"
			icon="lucide-eye"
			class="ml-auto shrink-0 opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
			:label="__('Preview')"
			@click.stop="$emit('preview', document)"
		/>
		<span class="shrink-0 tabular-nums text-ink-gray-7">{{ formatMoney(document.amount, currency) }}</span>
	</div>
	<!-- Each hint follows the value it judges, the pair kept tight and set apart from the next one -->
	<div v-else class="flex min-w-0 items-start gap-3">
		<DocumentTypeIcon :doctype="document.doctype" size="lg" />
		<div class="flex min-w-0 flex-1 flex-col self-stretch">
			<div class="flex items-center gap-4">
				<span class="flex min-w-0 items-center gap-1">
					<span class="truncate text-base-medium text-ink-gray-9">{{ title }}</span>
					<MatchHint
						v-if="party"
						:reasons="reasonsAbout('name', 'history')"
						:missing="__('Name not in the label')"
					/>
					<MatchHint :reasons="reasonsAbout('corrected')" />
				</span>
				<!-- The hint slot keeps its width, so amounts line up down the page whether a hint backs them or not -->
				<span class="ml-auto flex shrink-0 items-center gap-1">
					<span class="text-base tabular-nums text-ink-gray-7">{{ formatMoney(document.amount, currency) }}</span>
					<span class="flex w-4 justify-center">
						<MatchHint
							v-if="lineAmount !== null"
							:reasons="reasonsAbout('amount')"
							:mismatch="__('Different amount')"
						/>
					</span>
				</span>
			</div>
			<div class="mt-2 flex items-center gap-4 text-sm text-ink-gray-5">
				<span class="flex shrink-0 items-center gap-1">
					<a
						:href="deskUrl(document.doctype, document.name)"
						target="_blank"
						class="text-ink-gray-6 hover:text-ink-gray-8 hover:underline"
						@click.stop
						>{{ document.name }}</a
					>
					<MatchHint :reasons="reasonsAbout('reference')" :missing="__('Number not in the label')" />
				</span>
				<span v-if="reference" class="truncate">{{ reference }}</span>
				<slot name="note" />
				<span
					v-if="gap"
					class="ml-auto mr-5 shrink-0 rounded-3 bg-surface-amber-2 px-1 tabular-nums text-ink-amber-7"
					:title="__('Gap between the bank line and the document')"
				>
					{{ gap > 0 ? "+" : "−" }}{{ formatMoney(Math.abs(gap), currency) }}
				</span>
			</div>
			<!-- At the card's foot, level with the bank line's date beside it -->
			<span v-if="document.posting_date" class="mt-2 flex items-center gap-1 xl:mt-auto xl:pt-2">
				<DateLabel :date="document.posting_date" />
				<MatchHint :reasons="reasonsAbout('date')" :missing="__('The date gives no hint')" />
			</span>
		</div>
	</div>
</template>
