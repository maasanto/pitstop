<script setup>
import { Button, Dialog, ErrorMessage, LoadingText, TextInput, toast, useCall } from "frappe-ui";
import { ref, watch } from "vue";
import { DOCTYPE_ICONS, formatDate, formatMoney } from "../format";
import { __ } from "../translation";
import ConfidencePill from "./ConfidencePill.vue";
import MatchHint from "./MatchHint.vue";

const props = defineProps({
	// A document to open on directly, as the desk's "Find the bank line" link does
	doctype: { type: String, default: null },
	name: { type: String, default: null },
});
const open = defineModel("open", { type: Boolean, default: false });
const emit = defineEmits(["reconciled"]);

const query = ref("");
const document = ref(null);

const documents = useCall({
	url: "/api/v2/method/bank_matching.lookup.search_open_documents",
	immediate: false,
	params: () => ({ query: query.value }),
});
const lines = useCall({
	url: "/api/v2/method/bank_matching.lookup.get_lines_for_document",
	immediate: false,
	params: () => ({ doctype: document.value?.doctype, name: document.value?.name }),
});
const reconcile = useCall({
	url: "/api/v2/method/bank_matching.lookup.reconcile_document",
	method: "POST",
	immediate: false,
});

watch(query, () => query.value.trim().length >= 2 && documents.reload());
watch(open, (isOpen) => {
	if (isOpen && props.doctype && props.name) pick({ doctype: props.doctype, name: props.name });
	if (!isOpen) {
		query.value = "";
		document.value = null;
	}
});

function pick(row) {
	document.value = row;
	lines.reload();
}

const reasonsAbout = (proposal, ...signals) =>
	proposal.documents[0].reasons.filter((reason) => signals.includes(reason.signal));

async function reconcileWith(match) {
	await reconcile.submit({
		doctype: document.value.doctype,
		name: document.value.name,
		bank_transaction: match.line.name,
	});
	if (reconcile.error) return;
	toast.success(__("{0} reconciled with {1}", [document.value.name, match.line.description]));
	open.value = false;
	emit("reconciled");
}
</script>

<template>
	<Dialog v-model:open="open" size="3xl" :title="__('Find the line of a document')">
		<template v-if="!document">
			<TextInput
				v-model="query"
				:debounce="300"
				:placeholder="__('Invoice or payment number, party or amount')"
				autofocus
			>
				<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
			</TextInput>
			<div class="mt-3 max-h-[55vh] divide-y divide-outline-gray-1 overflow-y-auto">
				<LoadingText v-if="documents.loading && !documents.data" />
				<p v-else-if="documents.data && !documents.data.length" class="py-8 text-center text-p-sm text-ink-gray-4">
					{{ __("No open invoice or payment matches") }}
				</p>
				<button
					v-for="row in documents.data || []"
					:key="`${row.doctype}:${row.name}`"
					class="flex w-full items-center gap-2 rounded-4 px-2 py-2.5 text-left hover:bg-surface-gray-2"
					@click="pick(row)"
				>
					<span :class="DOCTYPE_ICONS[row.doctype]" class="size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
					<span class="text-base-medium text-ink-gray-9">{{ row.party_name }}</span>
					<span class="truncate text-sm text-ink-gray-5">
						{{ row.name }} · {{ __(row.doctype) }} · {{ formatDate(row.posting_date) }}
					</span>
					<span class="ml-auto shrink-0 text-base-semibold tabular-nums text-ink-gray-9">
						{{ formatMoney(row.amount) }}
					</span>
				</button>
			</div>
		</template>

		<template v-else>
			<div class="mb-4 flex items-center gap-2">
				<Button
					v-if="!doctype"
					variant="ghost"
					icon="lucide-arrow-left"
					:label="__('Back')"
					@click="document = null"
				/>
				<div v-if="lines.data" class="min-w-0">
					<div class="text-base-medium text-ink-gray-9">
						{{ lines.data.document.party_name || lines.data.document.name }}
						· {{ formatMoney(lines.data.document.amount) }}
					</div>
					<div class="text-sm text-ink-gray-5">{{ document.name }} · {{ __(document.doctype) }}</div>
				</div>
			</div>
			<ErrorMessage v-if="lines.error" :message="lines.error" />
			<LoadingText v-else-if="lines.loading" :text="__('Scoring the open bank lines…')" />
			<p v-else-if="lines.data && !lines.data.lines.length" class="py-8 text-center text-p-sm text-ink-gray-4">
				{{ __("No open bank line matches this document") }}
			</p>
			<div v-else-if="lines.data" class="max-h-[55vh] space-y-2 overflow-y-auto">
				<div
					v-for="match in lines.data.lines"
					:key="match.line.name"
					class="flex items-center gap-4 rounded-4 border border-outline-gray-1 px-3 py-2.5"
				>
					<div class="min-w-0 flex-1">
						<div class="truncate text-base-medium text-ink-gray-9">{{ match.line.description }}</div>
						<div class="mt-1 flex items-center gap-1.5 text-sm text-ink-gray-5">
							{{ formatDate(match.line.date) }}
							<MatchHint
								:reasons="reasonsAbout(match.proposal, 'reference')"
								:missing="__('Number not in the label')"
							/>
							<MatchHint
								:reasons="reasonsAbout(match.proposal, 'name', 'history')"
								:missing="__('Name not in the label')"
							/>
						</div>
					</div>
					<span class="flex items-center gap-1.5 text-base-semibold tabular-nums text-ink-gray-9">
						{{ formatMoney(match.line.amount, match.line.currency) }}
						<MatchHint
							:reasons="reasonsAbout(match.proposal, 'amount')"
							:missing="__('Different amount')"
						/>
					</span>
					<ConfidencePill :proposal="match.proposal" />
					<Button :label="__('Reconcile')" :loading="reconcile.loading" @click="reconcileWith(match)" />
				</div>
			</div>
			<ErrorMessage v-if="reconcile.error" class="mt-3" :message="reconcile.error" />
		</template>
	</Dialog>
</template>
