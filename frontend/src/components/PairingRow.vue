<script setup>
import { Button } from "frappe-ui";
import { computed, ref } from "vue";
import { formatDate, formatMoney } from "../format";
import DocumentCard from "./DocumentCard.vue";
import LevelBadge from "./LevelBadge.vue";
import SignalChip from "./SignalChip.vue";

const props = defineProps({
	pairing: { type: Object, required: true },
	chosen: { type: Object, required: true },
	approved: { type: Boolean, default: false },
	focused: { type: Boolean, default: false },
});
defineEmits(["toggle", "choose", "search", "preview"]);

const line = computed(() => props.pairing.line);
const alternatives = computed(() =>
	props.pairing.proposals.filter((proposal) => proposal.key !== props.chosen.key),
);
const showAlternatives = ref(false);
defineExpose({ toggleAlternatives: () => (showAlternatives.value = !showAlternatives.value) });
</script>

<template>
	<div
		class="group grid cursor-pointer grid-cols-[1.75rem_minmax(0,1fr)_7.5rem_1.25rem_minmax(0,1.35fr)] items-start gap-x-3 rounded-6 border px-3 py-2.5 transition-colors"
		:class="[
			approved
				? 'border-outline-green-3 bg-surface-green-1'
				: 'border-outline-gray-1 bg-surface-base hover:border-outline-gray-3',
			focused && 'ring-2 ring-outline-gray-4 ring-offset-1',
		]"
		@click="$emit('toggle')"
	>
		<button
			role="checkbox"
			:aria-checked="approved"
			:aria-label="approved ? __('Pre-approved') : __('Pre-approve')"
			class="mt-0.5 flex size-6 items-center justify-center rounded-full border-2 transition-colors"
			:class="
				approved
					? 'border-transparent bg-surface-green-6 text-ink-base'
					: 'border-outline-gray-3 text-transparent group-hover:border-outline-gray-5'
			"
			@click.stop="$emit('toggle')"
		>
			<span class="lucide-check size-3.5" aria-hidden="true" />
		</button>

		<div class="min-w-0 pt-0.5">
			<div class="truncate text-base-medium text-ink-gray-9" :title="line.description">
				{{ line.description }}
			</div>
			<div class="mt-1 flex items-center gap-1.5 text-sm text-ink-gray-5">
				<span
					:class="
						line.amount > 0
							? 'lucide-arrow-down-left text-ink-green-6'
							: 'lucide-arrow-up-right text-ink-red-5'
					"
					class="size-3.5"
					aria-hidden="true"
				/>
				{{ formatDate(line.date) }}
				<span v-if="line.bank_party_name" class="truncate">{{ line.bank_party_name }}</span>
			</div>
		</div>

		<div class="pt-0.5 text-right text-lg-semibold tabular-nums text-ink-gray-9">
			{{ formatMoney(line.amount, line.currency) }}
		</div>

		<span class="lucide-arrow-right mt-1.5 size-4 text-ink-gray-4" aria-hidden="true" />

		<div class="min-w-0 space-y-1.5">
			<div v-if="chosen.settlement" class="rounded-4 border border-outline-gray-1 bg-surface-gray-1">
				<div class="flex items-center gap-1.5 px-2.5 pb-1 pt-2">
					<span class="lucide-layers size-4 text-ink-gray-6" aria-hidden="true" />
					<span class="text-base-medium text-ink-gray-9">{{
						__("{0} payments settled at once", [chosen.documents.length])
					}}</span>
					<span class="ml-auto text-base-semibold tabular-nums text-ink-gray-9">
						{{ formatMoney(chosen.settlement.total, line.currency) }}
					</span>
				</div>
				<div class="flex gap-1 px-2.5 pb-1">
					<SignalChip v-for="reason in chosen.settlement.reasons" :key="reason.signal" :reason="reason" />
				</div>
				<div class="divide-y divide-outline-gray-1 border-t border-outline-gray-1">
					<DocumentCard
						v-for="document in chosen.documents"
						:key="document.name"
						compact
						:document="document"
						:currency="line.currency"
						@preview="$emit('preview', $event)"
					/>
				</div>
			</div>
			<DocumentCard
				v-for="document in chosen.settlement ? [] : chosen.documents"
				:key="document.name"
				:document="document"
				:currency="line.currency"
				:line-amount="chosen.settlement ? null : line.amount"
				@preview="$emit('preview', $event)"
			>
				<template v-if="chosen.creates_payment" #note>
					<span class="mt-1 flex items-center gap-1 text-sm text-ink-blue-5">
						<span class="lucide-circle-plus size-3.5" aria-hidden="true" />
						{{ __("Payment created on validation") }}
					</span>
				</template>
			</DocumentCard>
			<p v-if="chosen.settlement?.fee" class="text-p-sm text-ink-amber-7">
				{{
					__("{0} less than the payments, likely card fees: it stays open on the last payment", [
						formatMoney(chosen.settlement.fee, line.currency),
					])
				}}
			</p>
			<div class="flex gap-3 text-sm text-ink-gray-5" @click.stop>
				<button
					v-if="alternatives.length"
					class="flex items-center gap-1 rounded-3 hover:text-ink-gray-8"
					@click="showAlternatives = !showAlternatives"
				>
					<span
						:class="showAlternatives ? 'lucide-chevron-down' : 'lucide-chevron-right'"
						class="size-3.5"
						aria-hidden="true"
					/>
					{{ __("Other leads ({0})", [alternatives.length]) }}
				</button>
				<button
					class="flex items-center gap-1 rounded-3 opacity-0 transition-opacity hover:text-ink-gray-8 focus-visible:opacity-100 group-hover:opacity-100"
					:class="focused && 'opacity-100'"
					@click="$emit('search')"
				>
					<span class="lucide-search size-3.5" aria-hidden="true" />
					{{ __("Not this one? Search another document") }}
				</button>
			</div>
			<div v-if="showAlternatives" class="space-y-1.5 border-l-2 border-outline-gray-2 pl-3" @click.stop>
				<div v-for="proposal in alternatives" :key="proposal.key" class="flex items-start gap-2">
					<div class="min-w-0 flex-1 space-y-1.5">
						<DocumentCard
							v-for="document in proposal.documents"
							:key="document.name"
							:document="document"
							:currency="line.currency"
							:line-amount="proposal.settlement ? null : line.amount"
							@preview="$emit('preview', $event)"
						/>
					</div>
					<div class="flex flex-col items-end gap-1.5">
						<LevelBadge :level="proposal.level" />
						<Button size="sm" :label="__('Use this one')" @click="$emit('choose', proposal)" />
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
