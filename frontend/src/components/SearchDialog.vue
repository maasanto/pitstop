<script setup>
import { Button, Dialog, LoadingText, TextInput, useCall } from "frappe-ui";
import { computed, reactive, ref, watch } from "vue";
import { descriptionText, formatMoney } from "../format";
import { __, _n } from "../translation";
import ProposalOption from "./ProposalOption.vue";

const props = defineProps({
	line: { type: Object, default: null },
	// The line's proposals, shown above the search results while nothing is typed
	leads: { type: Array, default: () => [] },
	currentKey: { type: String, default: null },
	refused: { type: Array, default: () => [] },
});
const open = defineModel("open", { type: Boolean, default: false });
const emit = defineEmits(["choose", "preview"]);

const query = ref("");
const results = useCall({
	url: "/api/v2/method/pitstop.api.search",
	immediate: false,
	params: () => ({ bank_transaction: props.line?.name, query: query.value }),
});

// Documents picked to pay the line together, kept across searches
const picked = reactive(new Map());

watch([open, query], () => open.value && props.line && results.reload());
watch(open, (isOpen) => {
	if (isOpen) return;
	query.value = "";
	picked.clear();
});

const showLeads = computed(() => !query.value.trim());
const leadKeys = computed(() => new Set(props.leads.map((lead) => lead.key)));
// Until something is typed, only the documents with some signal: the rest is every open document
const otherDocuments = computed(() =>
	(results.data || []).filter(
		(proposal) => !showLeads.value || (proposal.score > 0 && !leadKeys.value.has(proposal.key)),
	),
);

// The reconciliation takes documents of a single type
const pickedDoctype = computed(() => [...picked.values()][0]?.documents[0].doctype);
const pickedTotal = computed(() =>
	[...picked.values()].reduce((sum, proposal) => sum + proposal.documents[0].amount, 0),
);
const pickedGap = computed(() =>
	props.line ? Math.round((Math.abs(props.line.amount) - pickedTotal.value) * 100) / 100 : 0,
);

function isPickable(proposal) {
	return !pickedDoctype.value || proposal.documents[0]?.doctype === pickedDoctype.value;
}

function setPick(proposal, isPicked) {
	isPicked ? picked.set(proposal.key, proposal) : picked.delete(proposal.key);
}

function actionLabel(proposal) {
	if (proposal.key === props.currentKey) return __("Proposed");
	return props.refused.includes(proposal.key) ? __("Restore") : __("Use this one");
}

function choose(proposal) {
	emit("choose", proposal);
	open.value = false;
}

function choosePicked() {
	const proposals = [...picked.values()];
	choose({
		key: `manual:${proposals.map((proposal) => proposal.key).join(",")}`,
		level: "high",
		score: null,
		documents: proposals.map((proposal) => proposal.documents[0]),
		creates_payment: proposals.some((proposal) => proposal.creates_payment),
	});
}
</script>

<template>
	<Dialog v-model:open="open" size="3xl" :title="__('Pick the right document')">
		<p v-if="line" class="mb-3 text-p-sm text-ink-gray-6">
			{{ descriptionText(line.description) }} · {{ formatMoney(line.amount, line.currency) }}
		</p>
		<TextInput v-model="query" :debounce="300" :placeholder="__('Number, party or amount')" autofocus>
			<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
		</TextInput>
		<p class="mt-2 text-p-sm text-ink-gray-5">
			{{ __("Select one document, or several when this line pays them together.") }}
		</p>
		<div v-if="line" class="mt-4 max-h-[55vh] space-y-5 overflow-y-auto">
			<section v-if="showLeads">
				<h3 class="mb-2 text-sm-medium text-ink-gray-6">{{ __("Leads from Dokos") }}</h3>
				<p v-if="!leads.length" class="text-p-sm text-ink-gray-5">
					{{ __("No lead: search the document above.") }}
				</p>
				<div class="space-y-2">
					<ProposalOption
						v-for="proposal in leads"
						:key="proposal.key"
						:proposal="proposal"
						:line="line"
						:action-label="actionLabel(proposal)"
						:is-current="proposal.key === currentKey"
						:is-refused="refused.includes(proposal.key)"
						:is-picked="picked.has(proposal.key)"
						:is-pickable="isPickable(proposal)"
						@choose="choose(proposal)"
						@preview="$emit('preview', $event)"
						@pick="setPick(proposal, $event)"
					/>
				</div>
			</section>

			<section>
				<h3 class="mb-2 text-sm-medium text-ink-gray-6">
					{{ showLeads ? __("Other open documents") : __("Search results") }}
				</h3>
				<LoadingText v-if="results.loading && !results.data" />
				<p v-else-if="results.data && !otherDocuments.length" class="py-6 text-center text-p-sm text-ink-gray-4">
					{{ showLeads ? __("Type a number, a party or an amount to search every open document") : __("No open document matches") }}
				</p>
				<div class="space-y-2">
					<ProposalOption
						v-for="proposal in otherDocuments"
						:key="proposal.key"
						:proposal="proposal"
						:line="line"
						:action-label="__('Use this one')"
						:is-picked="picked.has(proposal.key)"
						:is-pickable="isPickable(proposal)"
						@choose="choose(proposal)"
						@preview="$emit('preview', $event)"
						@pick="setPick(proposal, $event)"
					/>
				</div>
			</section>
		</div>
		<div v-if="picked.size" class="mt-4 border-t border-outline-gray-1 pt-4">
			<div class="flex items-center gap-3">
				<span class="text-base text-ink-gray-7">
					{{ _n(picked.size, __("1 document"), __("{0} documents", [picked.size])) }} ·
					<b class="tabular-nums text-ink-gray-9">{{ formatMoney(pickedTotal, line?.currency) }}</b>
					<span
						v-if="pickedGap"
						class="ml-1 rounded-3 bg-surface-amber-2 px-1 text-sm tabular-nums text-ink-amber-7"
						>{{ pickedGap > 0 ? "+" : "−" }}{{ formatMoney(Math.abs(pickedGap), line?.currency) }}</span
					>
				</span>
				<Button class="ml-auto" :label="__('Clear')" variant="ghost" @click="picked.clear()" />
				<Button
					variant="solid"
					:label="_n(picked.size, __('Use this document'), __('Use these {0} documents', [picked.size]))"
					@click="picked.size > 1 ? choosePicked() : choose([...picked.values()][0])"
				/>
			</div>
		</div>
	</Dialog>
</template>
