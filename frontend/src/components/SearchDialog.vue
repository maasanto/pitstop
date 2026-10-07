<script setup>
import { Button, Dialog, LoadingText, Switch, TextInput, useCall } from "frappe-ui";
import { computed, reactive, ref, toRef, watch } from "vue";
import { descriptionText, formatMoney } from "../format";
import { usePicking } from "../picking";
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
const { picked, pickedTotal, pickedGap, isPickable, setPick, pickedProposal } = usePicking(toRef(props, "line"));

watch([open, query], () => open.value && props.line && results.reload());
watch(open, (isOpen) => {
	if (isOpen) return;
	query.value = "";
	picked.clear();
});

const showLeads = computed(() => !query.value.trim());
const leadKeys = computed(() => new Set(props.leads.map((lead) => lead.key)));

const exactAmountOnly = ref(false);
const hiddenDoctypes = reactive(new Set());
const doctypesFound = computed(() => [
	...new Set((results.data || []).map((proposal) => proposal.documents[0].doctype)),
]);

function passesFilters(document) {
	if (hiddenDoctypes.has(document.doctype)) return false;
	return !exactAmountOnly.value || Math.abs(document.amount - Math.abs(props.line.amount)) < 0.005;
}

const otherDocuments = computed(() =>
	(results.data || []).filter(
		(proposal) =>
			(!showLeads.value || !leadKeys.value.has(proposal.key)) && passesFilters(proposal.documents[0]),
	),
);

function actionLabel(proposal) {
	if (proposal.key === props.currentKey) return __("Proposed");
	return props.refused.includes(proposal.key) ? __("Restore") : __("Use this one");
}

function choose(proposal) {
	emit("choose", proposal);
	open.value = false;
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
		<div class="mt-3 flex flex-wrap items-center gap-x-6 gap-y-1">
			<Switch v-model="exactAmountOnly" size="sm" :label="__('Show only exact amount')" />
			<Switch
				v-for="doctype in doctypesFound"
				:key="doctype"
				size="sm"
				:label="__(doctype)"
				:model-value="!hiddenDoctypes.has(doctype)"
				@update:model-value="(isShown) => (isShown ? hiddenDoctypes.delete(doctype) : hiddenDoctypes.add(doctype))"
			/>
		</div>
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
					{{ __("No open document matches") }}
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
					@click="choose(pickedProposal())"
				/>
			</div>
		</div>
	</Dialog>
</template>
