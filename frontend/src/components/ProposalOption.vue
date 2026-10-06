<script setup>
import { Button, Checkbox } from "frappe-ui";
import { computed } from "vue";
import { formatMoney } from "../format";
import ConfidencePill from "./ConfidencePill.vue";
import DocumentCard from "./DocumentCard.vue";

const props = defineProps({
	proposal: { type: Object, required: true },
	line: { type: Object, required: true },
	actionLabel: { type: String, required: true },
	isCurrent: { type: Boolean, default: false },
	isRefused: { type: Boolean, default: false },
	// Several single documents of one type can pay the line together
	isPicked: { type: Boolean, default: false },
	isPickable: { type: Boolean, default: false },
});
defineEmits(["choose", "preview", "pick"]);

const single = computed(() => !props.proposal.rule && !props.proposal.settlement && props.proposal.documents[0]);
</script>

<template>
	<div class="flex items-start gap-3" :class="isRefused && 'opacity-60'">
		<div class="w-5 shrink-0 pt-2.5">
			<Checkbox
				v-if="single"
				:model-value="isPicked"
				:disabled="!isPickable && !isPicked"
				:aria-label="__('Add to the documents paid by this line')"
				@update:model-value="(isChecked) => $emit('pick', isChecked)"
			/>
		</div>
		<div
			class="min-w-0 flex-1 rounded-4 border px-3 py-2"
			:class="isPicked ? 'border-outline-gray-4' : 'border-outline-gray-1'"
		>
			<template v-if="proposal.rule">
				<div class="flex items-center gap-1.5 text-base-medium text-ink-gray-9">
					<span class="lucide-wand-sparkles size-4 text-ink-blue-6" aria-hidden="true" />
					{{ proposal.rule.rule_name }}
				</div>
				<div class="mt-1.5 text-sm text-ink-gray-5">
					{{
						proposal.rule.classify_as === "Payment Entry"
							? __("Creates a payment to {0}", [proposal.rule.party])
							: __("Creates a bank entry on {0}", [proposal.rule.account])
					}}
				</div>
			</template>
			<template v-else-if="proposal.settlement">
				<div class="flex items-center gap-1.5 text-base-medium text-ink-gray-9">
					<span class="lucide-layers size-4 text-ink-gray-6" aria-hidden="true" />
					{{ __("{0} payments settled at once", [proposal.documents.length]) }}
					<span class="ml-auto tabular-nums">{{ formatMoney(proposal.settlement.total, line.currency) }}</span>
				</div>
				<div class="mt-1 divide-y divide-outline-gray-1">
					<DocumentCard
						v-for="document in proposal.documents"
						:key="document.name"
						compact
						:document="document"
						:currency="line.currency"
						@preview="$emit('preview', $event)"
					/>
				</div>
			</template>
			<DocumentCard v-else :document="single" :currency="line.currency" :line-amount="line.amount" />
		</div>
		<div class="flex w-36 shrink-0 flex-col items-end gap-1.5">
			<ConfidencePill :proposal="proposal" />
			<div class="flex gap-1">
				<Button
					v-if="single"
					variant="ghost"
					icon="lucide-eye"
					:tooltip="__('Preview')"
					:label="__('Preview')"
					@click="$emit('preview', single)"
				/>
				<Button :label="actionLabel" :disabled="isCurrent" @click="$emit('choose')" />
			</div>
		</div>
	</div>
</template>
