<script setup>
import { Button, Combobox, Dialog, ErrorMessage, FormControl, toast, useCall } from "frappe-ui";
import { computed, ref, watch } from "vue";
import { formatMoney } from "../format";
import { __ } from "../translation";

const props = defineProps({ line: { type: Object, default: null } });
const open = defineModel("open", { type: Boolean, default: false });
const emit = defineEmits(["created"]);

const ruleName = ref("");
const contains = ref("");
const account = ref(null);

const accounts = useCall({
	url: "/api/v2/method/bank_matching.api.get_bookable_accounts",
	immediate: false,
	params: () => ({ bank_transaction: props.line?.name }),
});
const accountOptions = computed(() =>
	(accounts.data || []).map((row) => ({ label: row.name, value: row.name })),
);

const create = useCall({
	url: "/api/v2/method/bank_matching.api.create_rule",
	method: "POST",
	immediate: false,
});

// The words before the first digit are what recurs: "FRAIS TENUE DE COMPTE SEPTEMBRE 0042" → "FRAIS TENUE DE COMPTE SEPTEMBRE"
function recurringPart(description) {
	return (description || "").split(/\d/)[0].replace(/[\s/·-]+$/, "").trim();
}

watch(open, (isOpen) => {
	if (!isOpen || !props.line) return;
	contains.value = recurringPart(props.line.description);
	ruleName.value = contains.value.toLowerCase().replace(/^./, (letter) => letter.toUpperCase());
	account.value = null;
	accounts.reload();
});

async function submit() {
	await create.submit({
		bank_transaction: props.line.name,
		rule_name: ruleName.value,
		contains: contains.value,
		account: account.value,
	});
	if (create.error) return;
	toast.success(__("Rule {0} created", [ruleName.value]));
	open.value = false;
	emit("created");
}
</script>

<template>
	<Dialog v-model:open="open" size="xl" :title="__('Always book such lines')">
		<p v-if="line" class="mb-4 text-p-sm text-ink-gray-6">
			{{ line.description }} · {{ formatMoney(line.amount, line.currency) }}
		</p>
		<div class="space-y-4">
			<FormControl v-model="contains" :label="__('When the label contains')" />
			<FormControl v-model="ruleName" :label="__('Rule name')" />
			<div>
				<div class="mb-1.5 text-xs text-ink-gray-5">{{ __("Book it on the account") }}</div>
				<Combobox v-model="account" :options="accountOptions" :placeholder="__('Search an account')" />
			</div>
			<p class="text-p-sm text-ink-gray-5">
				{{
					__(
						"Dokos then proposes a bank entry for every such line; validating creates it. The rule is a Bank Transaction Rule you can refine in the desk.",
					)
				}}
			</p>
			<ErrorMessage v-if="create.error" :message="create.error" />
		</div>
		<template #actions>
			<Button
				variant="solid"
				class="w-full"
				:label="__('Create the rule')"
				:disabled="!contains.trim() || !ruleName.trim() || !account"
				:loading="create.loading"
				@click="submit"
			/>
		</template>
	</Dialog>
</template>
