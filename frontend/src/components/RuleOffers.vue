<script setup>
import { Button, call, toast } from "frappe-ui";
import { ref } from "vue";
import { __, _n } from "../translation";

const props = defineProps({
	offers: { type: Array, required: true },
	bankAccount: { type: String, required: true },
});
const emit = defineEmits(["answered"]);

const answering = ref(null);
const offerId = (offer) => `${offer.transaction_type}:${offer.key}`;

function title(offer) {
	if (!offer.party) return __("Always book “{0}” lines on the account {1}?", [offer.key, offer.account_label]);
	return offer.transaction_type === "Deposit"
		? __("Always record “{0}” lines as payments from {1}?", [offer.key, offer.party_name])
		: __("Always record “{0}” lines as payments to {1}?", [offer.key, offer.party_name]);
}

async function answer(offer, method, message) {
	answering.value = offerId(offer);
	try {
		await call(`pitstop.api.${method}`, {
			bank_account: props.bankAccount,
			key: offer.key,
			transaction_type: offer.transaction_type,
		});
		toast.success(message);
		emit("answered");
	} catch (error) {
		toast.error(error.messages?.[0] || error.message);
	} finally {
		answering.value = null;
	}
}
</script>

<template>
	<section class="mb-10 space-y-2" :aria-label="__('Rules to create')">
		<div
			v-for="offer in offers"
			:key="offerId(offer)"
			class="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-6 border border-outline-gray-1 bg-surface-gray-1 px-6 py-4"
		>
			<span class="lucide-wand-sparkles size-5 shrink-0 text-ink-blue-6" aria-hidden="true" />
			<div class="min-w-0 flex-1">
				<p class="text-base-medium text-ink-gray-9">{{ title(offer) }}</p>
				<p class="mt-1 text-p-sm text-ink-gray-6">
					{{ __("You booked them that way the last {0} times", [offer.booked]) }} ·
					{{
						_n(
							offer.lines.length,
							__("the rule books 1 open line"),
							__("the rule books {0} open lines", [offer.lines.length]),
						)
					}}
				</p>
			</div>
			<Button
				variant="ghost"
				:label="__('No, never')"
				:disabled="answering === offerId(offer)"
				@click="answer(offer, 'decline_rule_offer', __('Dokos will not offer this rule again'))"
			/>
			<Button
				variant="solid"
				icon-left="lucide-wand-sparkles"
				:label="__('Create the rule')"
				:loading="answering === offerId(offer)"
				@click="answer(offer, 'accept_rule_offer', __('Rule created: these lines are now proposed for validation'))"
			/>
		</div>
	</section>
</template>
