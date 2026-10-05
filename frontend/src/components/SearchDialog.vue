<script setup>
import { Button, Dialog, LoadingText, TextInput, useCall } from "frappe-ui";
import { ref, watch } from "vue";
import { formatMoney } from "../format";
import DocumentCard from "./DocumentCard.vue";

const props = defineProps({ line: { type: Object, default: null } });
const open = defineModel("open", { type: Boolean, default: false });
const emit = defineEmits(["choose", "preview"]);

const query = ref("");
const results = useCall({
	url: "/api/v2/method/bank_matching.api.search",
	immediate: false,
	params: () => ({ bank_transaction: props.line?.name, query: query.value }),
});

watch([open, query], () => open.value && props.line && results.reload());
watch(open, (isOpen) => isOpen || (query.value = ""));

function choose(proposal) {
	emit("choose", proposal);
	open.value = false;
}
</script>

<template>
	<Dialog v-model:open="open" size="3xl" :title="__('Search a document')">
		<p v-if="line" class="mb-3 text-p-sm text-ink-gray-6">
			{{ line.description }} · {{ formatMoney(line.amount, line.currency) }}
		</p>
		<TextInput v-model="query" :debounce="300" :placeholder="__('Number, party or amount')" autofocus>
			<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
		</TextInput>
		<div class="mt-3 max-h-[55vh] space-y-2 overflow-y-auto">
			<LoadingText v-if="results.loading && !results.data" />
			<p v-else-if="results.data && !results.data.length" class="py-10 text-center text-p-sm text-ink-gray-4">
				{{ __("No open document matches") }}
			</p>
			<div v-for="proposal in results.data || []" :key="proposal.key" class="flex items-start gap-2">
				<DocumentCard
					class="min-w-0 flex-1"
					:document="proposal.documents[0]"
					:currency="line?.currency"
					@preview="$emit('preview', $event)"
				/>
				<Button :label="__('Use this one')" @click="choose(proposal)" />
			</div>
		</div>
	</Dialog>
</template>
