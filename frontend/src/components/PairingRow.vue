<script setup>
import { Button, Dropdown, Tooltip } from "frappe-ui";
import { computed } from "vue";
import { formatDate, formatMoney } from "../format";
import { __ } from "../translation";
import DocumentCard from "./DocumentCard.vue";
import MatchHint from "./MatchHint.vue";

const props = defineProps({
	pairing: { type: Object, required: true },
	chosen: { type: Object, required: true },
	approved: { type: Boolean, default: false },
	focused: { type: Boolean, default: false },
});
const emit = defineEmits(["toggle", "refuse", "search", "preview", "create-rule"]);

const line = computed(() => props.pairing.line);
const otherLeads = computed(() => props.pairing.proposals.length - 1);
const documentsTotal = computed(() => props.chosen.documents.reduce((sum, d) => sum + d.amount, 0));
const settlementReasons = (signal) => props.chosen.settlement.reasons.filter((r) => r.signal === signal);
const actions = computed(() => [
	{
		label: otherLeads.value > 0 ? __("Other leads ({0})", [otherLeads.value]) : __("Search a document"),
		icon: "lucide-list",
		shortcut: "O",
		onClick: () => emit("search"),
	},
	{ label: __("Not this one"), icon: "lucide-thumbs-down", shortcut: "X", onClick: () => emit("refuse") },
	{ label: __("Always book such lines…"), icon: "lucide-wand-sparkles", onClick: () => emit("create-rule") },
]);
</script>

<template>
	<div
		class="group grid cursor-pointer grid-cols-[1.5rem_minmax(0,0.85fr)_7rem_minmax(0,1.4fr)_6.5rem] items-start gap-x-6 rounded-6 border px-6 py-5 transition-colors"
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
			class="flex size-6 items-center justify-center rounded-full border-2 transition-colors"
			:class="
				approved
					? 'border-transparent bg-surface-green-6 text-ink-base'
					: 'border-outline-gray-3 text-transparent group-hover:border-outline-gray-5'
			"
			@click.stop="$emit('toggle')"
		>
			<span class="lucide-check size-3.5" aria-hidden="true" />
		</button>

		<div class="min-w-0">
			<div class="line-clamp-2 break-words text-base-medium !leading-5 text-ink-gray-9" :title="line.description">
				{{ line.description }}
			</div>
			<div class="mt-2 flex items-center gap-1.5 text-sm text-ink-gray-5">
				<span
					:class="
						line.amount > 0
							? 'lucide-arrow-down-left text-ink-green-7'
							: 'lucide-arrow-up-right text-ink-red-6'
					"
					class="size-4 shrink-0"
					aria-hidden="true"
				/>
				{{ formatDate(line.date) }}
				<span v-if="line.bank_party_name" class="truncate">· {{ line.bank_party_name }}</span>
			</div>
		</div>

		<div class="text-right text-xl-semibold tabular-nums text-ink-gray-9">
			{{ formatMoney(line.amount, line.currency) }}
		</div>

		<div class="min-w-0 border-l border-outline-gray-1 pl-6">
			<div v-if="chosen.rule" class="min-w-0">
				<div class="flex items-center gap-1.5">
					<span class="lucide-wand-sparkles size-4 shrink-0 text-ink-blue-6" aria-hidden="true" />
					<span class="truncate text-base-medium text-ink-gray-9">{{ chosen.rule.rule_name }}</span>
					<span class="ml-auto shrink-0 pl-2 text-base tabular-nums text-ink-gray-7">
						{{ formatMoney(Math.abs(line.amount), line.currency) }}
					</span>
				</div>
				<div class="mt-2 truncate text-sm text-ink-gray-5">
					{{
						chosen.rule.classify_as === "Payment Entry"
							? __("Creates a payment to {0}", [chosen.rule.party])
							: __("Creates a bank entry on {0}", [chosen.rule.account])
					}}
				</div>
			</div>
			<template v-else-if="chosen.settlement">
				<div class="flex items-center gap-1.5">
					<span class="lucide-layers size-4 shrink-0 text-ink-gray-6" aria-hidden="true" />
					<span class="truncate text-base-medium text-ink-gray-9">{{
						__("{0} payments settled at once", [chosen.documents.length])
					}}</span>
					<MatchHint :reasons="settlementReasons('batch')" />
					<span class="ml-auto shrink-0 pl-2 text-base tabular-nums text-ink-gray-7">
						{{ formatMoney(chosen.settlement.total, line.currency) }}
					</span>
					<MatchHint :reasons="settlementReasons('amount')" />
				</div>
				<div class="mt-2 divide-y divide-outline-gray-1">
					<DocumentCard
						v-for="document in chosen.documents"
						:key="document.name"
						compact
						:document="document"
						:currency="line.currency"
						@preview="$emit('preview', $event)"
					/>
				</div>
				<p v-if="chosen.settlement.fee" class="mt-2 text-p-sm text-ink-amber-7">
					{{
						__("{0} less than the payments, likely card fees: it stays open on the last payment", [
							formatMoney(chosen.settlement.fee, line.currency),
						])
					}}
				</p>
			</template>
			<div v-else-if="chosen.documents.length > 1" class="min-w-0">
				<div class="flex items-center gap-1.5">
					<span class="lucide-files size-4 shrink-0 text-ink-gray-6" aria-hidden="true" />
					<span class="truncate text-base-medium text-ink-gray-9">{{
						__("{0} documents paid at once", [chosen.documents.length])
					}}</span>
					<span class="ml-auto shrink-0 pl-2 text-base tabular-nums text-ink-gray-7">
						{{ formatMoney(documentsTotal, line.currency) }}
					</span>
				</div>
				<div class="mt-2 divide-y divide-outline-gray-1">
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
				v-else
				:document="chosen.documents[0]"
				:currency="line.currency"
				:line-amount="line.amount"
			>
				<template v-if="chosen.creates_payment" #note>
					<Tooltip :text="__('Payment created on validation')">
						<span
							class="lucide-circle-plus size-3.5 shrink-0 text-ink-blue-5"
							role="img"
							:aria-label="__('Payment created on validation')"
						/>
					</Tooltip>
				</template>
			</DocumentCard>
		</div>

		<!-- The section already names the confidence, and a rule shows its wand: only a pick of yours is flagged -->
		<div class="flex items-center justify-end gap-1" @click.stop>
			<Tooltip v-if="chosen.manual" :text="__('Chosen by you')">
				<span class="lucide-user-check size-4 shrink-0 text-ink-blue-6" role="img" :aria-label="__('Chosen by you')" />
			</Tooltip>
			<div
				class="flex items-center gap-0.5 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
				:class="focused ? 'opacity-100' : 'opacity-0'"
			>
				<Button
					v-if="chosen.documents.length === 1"
					variant="ghost"
					icon="lucide-eye"
					:tooltip="__('Preview')"
					:label="__('Preview')"
					@click="$emit('preview', chosen.documents[0])"
				/>
				<Button
					variant="ghost"
					icon="lucide-thumbs-down"
					:tooltip="__('Not this one')"
					:label="__('Not this one')"
					@click="$emit('refuse')"
				/>
				<Dropdown align="end" :options="actions">
					<template #trigger="{ open }">
						<Button variant="ghost" icon="lucide-ellipsis" :active="open" :label="__('More actions')" />
					</template>
					<template #item-suffix="{ item }">
						<kbd v-if="item.shortcut" class="font-sans text-xs text-ink-gray-5">{{ item.shortcut }}</kbd>
					</template>
				</Dropdown>
			</div>
		</div>
	</div>
</template>
