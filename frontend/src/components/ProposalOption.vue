<script setup>
import { Button } from "frappe-ui";
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
const emit = defineEmits(["choose", "preview", "pick"]);

const single = computed(() => !props.proposal.rule && !props.proposal.settlement && props.proposal.documents[0]);
// A rule or a settlement pays the line on its own: only its button chooses it
const canPick = computed(() => single.value && (props.isPickable || props.isPicked));

// Selecting a number to copy it is not a pick
function togglePick() {
	if (!canPick.value || window.getSelection()?.isCollapsed === false) return;
	emit("pick", !props.isPicked);
}
</script>

<template>
	<div
		:role="single ? 'checkbox' : undefined"
		:aria-checked="single ? isPicked : undefined"
		:aria-disabled="single && !canPick ? true : undefined"
		:tabindex="canPick ? 0 : undefined"
		:title="single && !canPick ? __('Only documents of the same type can be paid together') : undefined"
		class="flex items-start gap-3 rounded-4 border px-3 py-2 transition-colors"
		:class="[
			isPicked ? 'border-outline-gray-5 bg-surface-gray-2' : 'border-outline-gray-1',
			canPick && !isPicked && 'cursor-pointer hover:border-outline-gray-3 hover:bg-surface-gray-1',
			canPick && isPicked && 'cursor-pointer',
			(isRefused || (single && !canPick)) && 'opacity-60',
		]"
		@click="togglePick"
		@keydown.space.self.prevent="togglePick"
		@keydown.enter.self.prevent="togglePick"
	>
		<div class="min-w-0 flex-1">
			<template v-if="proposal.rule">
				<div class="flex items-center gap-1.5 text-base-medium text-ink-gray-9">
					<span class="lucide-wand-sparkles size-4 text-ink-blue-6" aria-hidden="true" />
					{{ proposal.rule.rule_name }}
				</div>
				<div class="mt-1.5 text-sm text-ink-gray-5">
					{{
						proposal.rule.classify_as === "Payment Entry"
							? __("Creates a payment to {0}", [proposal.rule.party])
							: __("Creates a bank entry on {0}", [proposal.rule.account_label])
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
					@click.stop="$emit('preview', single)"
				/>
				<Button :label="actionLabel" :disabled="isCurrent" @click.stop="$emit('choose')" />
			</div>
		</div>
	</div>
</template>
