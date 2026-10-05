<script setup>
import { Button } from "frappe-ui";
import { computed } from "vue";
import { DOCTYPE_ICONS, deskUrl, formatDate, formatMoney } from "../format";
import SignalChip from "./SignalChip.vue";

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
</script>

<template>
	<div v-if="compact" class="flex items-center gap-1.5 px-2.5 py-1.5 text-base">
		<a
			:href="deskUrl(document.doctype, document.name)"
			target="_blank"
			class="shrink-0 text-ink-gray-8 hover:underline"
			@click.stop
			>{{ document.name }}</a
		>
		<span class="truncate text-ink-gray-6">· {{ document.party_name || document.party }}</span>
		<span class="shrink-0 text-sm text-ink-gray-5">{{ formatDate(document.posting_date) }}</span>
		<span class="ml-auto shrink-0 tabular-nums text-ink-gray-8">{{
			formatMoney(document.amount, currency)
		}}</span>
		<Button
			variant="ghost"
			size="sm"
			icon="lucide-eye"
			:aria-label="__('Preview')"
			@click.stop="$emit('preview', document)"
		/>
	</div>
	<div v-else class="rounded-4 border border-outline-gray-1 bg-surface-gray-1 px-2.5 py-2">
		<div class="flex items-center gap-1.5">
			<span
				:class="DOCTYPE_ICONS[document.doctype]"
				class="size-4 shrink-0 text-ink-gray-6"
				aria-hidden="true"
			/>
			<a
				:href="deskUrl(document.doctype, document.name)"
				target="_blank"
				class="truncate text-base-medium text-ink-gray-9 hover:underline"
				@click.stop
				>{{ document.name }}</a
			>
			<span v-if="document.party_name || document.party" class="truncate text-base text-ink-gray-7">
				· {{ document.party_name || document.party }}
			</span>
			<span class="ml-auto shrink-0 text-base-semibold tabular-nums text-ink-gray-9">
				{{ formatMoney(document.amount, currency) }}
			</span>
			<span
				v-if="gap"
				class="shrink-0 rounded-3 bg-surface-amber-2 px-1 text-sm tabular-nums text-ink-amber-7"
				:title="__('Gap between the bank line and the document')"
			>
				{{ gap > 0 ? "+" : "−" }}{{ formatMoney(Math.abs(gap), currency) }}
			</span>
		</div>
		<div class="mt-1.5 flex items-center gap-2 text-sm text-ink-gray-5">
			<div v-if="document.reasons.length" class="flex gap-1">
				<SignalChip v-for="reason in document.reasons" :key="reason.signal" :reason="reason" />
			</div>
			<span class="truncate">
				{{ __(document.doctype) }}
				<template v-if="document.due_date"> · {{ __("due {0}", [formatDate(document.due_date)]) }}</template>
				<template v-else-if="document.posting_date"> · {{ formatDate(document.posting_date) }}</template>
				<template v-if="document.reference"> · {{ document.reference }}</template>
			</span>
			<Button
				class="ml-auto"
				variant="ghost"
				icon="lucide-eye"
				:tooltip="__('Preview')"
				:aria-label="__('Preview')"
				@click.stop="$emit('preview', document)"
			/>
		</div>
		<slot name="note" />
	</div>
</template>
