<script setup>
import { Button, Dropdown, LoadingText, Popover, Switch, TextInput, useCall } from "frappe-ui";
import { computed, reactive, ref, watch } from "vue";
import { DOCUMENT_TYPES, descriptionText, formatMoney } from "../format";
import { usePicking } from "../picking";
import { readStored, writeStored } from "../storage";
import { __, _n } from "../translation";
import DateLabel from "./DateLabel.vue";
import DocumentTypeIcon from "./DocumentTypeIcon.vue";
import ProposalOption from "./ProposalOption.vue";

const props = defineProps({
	pairings: { type: Array, required: true },
	// The ⋯ menu of a line: record a rule, create a payment
	actionsFor: { type: Function, required: true },
});
const emit = defineEmits(["choose", "preview", "restore"]);

const DOCTYPES = Object.keys(DOCUMENT_TYPES);
const FILTERS_KEY = "pitstop:match-filters";
// Every type and any amount until the user narrows it, then what they chose, as on /banking
const filters = reactive({ doctypes: [...DOCTYPES], exactAmount: false, ...readStored(FILTERS_KEY) });
watch(filters, () => writeStored(FILTERS_KEY, { ...filters }));

// Set, never toggle: a frappe-ui control may emit the same change twice
function setDoctype(doctype, isShown) {
	filters.doctypes = isShown
		? [...new Set([...filters.doctypes, doctype])]
		: filters.doctypes.filter((shown) => shown !== doctype);
}

const selectedName = ref(null);
const selected = computed(
	() => props.pairings.find((pairing) => pairing.line.name === selectedName.value) || props.pairings[0],
);
const line = computed(() => selected.value?.line);

const query = ref("");
const results = useCall({
	url: "/api/v2/method/pitstop.api.search",
	method: "POST",
	immediate: false,
	params: () => ({
		bank_transaction: line.value?.name,
		query: query.value,
		doctypes: filters.doctypes,
		exact_amount: filters.exactAmount,
	}),
});

const { picked, pickedTotal, pickedGap, isPickable, setPick, pickedProposal } = usePicking(line);

watch(
	() => line.value?.name,
	() => {
		query.value = "";
		picked.clear();
	},
);
watch(
	[() => line.value?.name, query, () => [...filters.doctypes], () => filters.exactAmount],
	() => line.value && filters.doctypes.length && results.submit(),
	{ immediate: true },
);

function choose(proposal) {
	emit("choose", selected.value, proposal);
}
</script>

<template>
	<div class="grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
		<div class="divide-y divide-outline-gray-1 border-y border-outline-gray-1">
			<div
				v-for="pairing in pairings"
				:key="pairing.line.name"
				role="button"
				tabindex="0"
				:aria-pressed="pairing === selected"
				class="flex cursor-pointer items-start gap-3 px-3 py-3 transition-colors"
				:class="pairing === selected ? 'bg-surface-gray-2' : 'hover:bg-surface-gray-1'"
				@click="selectedName = pairing.line.name"
				@keydown.enter.self.prevent="selectedName = pairing.line.name"
				@keydown.space.self.prevent="selectedName = pairing.line.name"
			>
				<div class="min-w-0 flex-1">
					<div class="line-clamp-2 break-words text-sm-medium text-ink-gray-9">{{ descriptionText(pairing.line.description) }}</div>
					<div class="mt-1 flex items-center gap-1.5 text-sm text-ink-gray-5">
						<DateLabel :date="pairing.line.date" />
						<template v-if="pairing.proposals.length">
							<span class="lucide-thumbs-down ml-1 size-3.5 shrink-0" aria-hidden="true" />
							<span class="truncate">{{ __("Leads refused") }}</span>
							<Button
								variant="ghost"
								size="xs"
								icon-left="lucide-undo-2"
								:label="__('Restore')"
								@click.stop="$emit('restore', pairing)"
							/>
						</template>
					</div>
				</div>
				<div class="shrink-0 text-right text-base-semibold tabular-nums text-ink-gray-9">
					{{ formatMoney(pairing.line.amount, pairing.line.currency) }}
				</div>
				<Dropdown align="end" :options="actionsFor(pairing)">
					<template #trigger="{ open }">
						<Button variant="ghost" icon="lucide-ellipsis" :active="open" :label="__('More actions')" />
					</template>
				</Dropdown>
			</div>
		</div>

		<div v-if="line" class="space-y-3 lg:sticky lg:top-4">
			<div class="flex items-center gap-2">
				<TextInput v-model="query" class="flex-1" :debounce="300" :placeholder="__('Number, party or amount')">
					<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
				</TextInput>
				<Popover align="end">
					<template #trigger="{ isOpen }">
						<Button
							variant="outline"
							icon="lucide-filter"
							:active="isOpen"
							:label="__('Documents to show')"
							:tooltip="__('Documents to show')"
						/>
					</template>
					<div class="w-64 space-y-3 p-3">
						<Switch
							:model-value="filters.exactAmount"
							:label="__('Show only exact amount')"
							@update:model-value="filters.exactAmount = $event"
						/>
						<hr class="border-outline-gray-1" />
						<Switch
							v-for="doctype in DOCTYPES"
							:key="doctype"
							:model-value="filters.doctypes.includes(doctype)"
							@update:model-value="setDoctype(doctype, $event)"
						>
							<template #label>
								<span class="flex items-center gap-2">
									<DocumentTypeIcon :doctype="doctype" />
									{{ __(doctype) }}
								</span>
							</template>
						</Switch>
					</div>
				</Popover>
			</div>
			<div class="max-h-[60vh] space-y-2 overflow-y-auto">
				<p v-if="!filters.doctypes.length" class="py-6 text-center text-p-sm text-ink-gray-4">
					{{ __("Turn on a document type to see its open documents") }}
				</p>
				<LoadingText v-else-if="results.loading && !results.data" />
				<p v-else-if="results.data && !results.data.length" class="py-6 text-center text-p-sm text-ink-gray-4">
					{{ __("No open document matches") }}
				</p>
				<template v-else>
					<ProposalOption
						v-for="proposal in results.data || []"
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
				</template>
			</div>
			<div v-if="picked.size" class="flex items-center gap-3 border-t border-outline-gray-1 pt-3">
				<span class="text-base text-ink-gray-7">
					{{ _n(picked.size, __("1 document"), __("{0} documents", [picked.size])) }} ·
					<b class="tabular-nums text-ink-gray-9">{{ formatMoney(pickedTotal, line.currency) }}</b>
					<span
						v-if="pickedGap"
						class="ml-1 rounded-3 bg-surface-amber-2 px-1 text-sm tabular-nums text-ink-amber-7"
						>{{ pickedGap > 0 ? "+" : "−" }}{{ formatMoney(Math.abs(pickedGap), line.currency) }}</span
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
	</div>
</template>
