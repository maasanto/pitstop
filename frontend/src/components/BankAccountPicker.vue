<script setup>
import { Button, Dropdown } from "frappe-ui";
import { computed } from "vue";
import { __ } from "../translation";

const account = defineModel({ type: String, default: null });
const props = defineProps({ accounts: { type: Array, required: true } });

const selected = computed(() => props.accounts.find((candidate) => candidate.name === account.value));
const options = computed(() => [
	{
		group: __("Bank accounts"),
		options: props.accounts.map((candidate) => ({
			label: candidate.account_name,
			description: candidate.account,
			icon: "lucide-landmark",
			selected: candidate.name === account.value,
			onClick: () => (account.value = candidate.name),
		})),
	},
]);
</script>

<template>
	<Dropdown align="start" :options="options">
		<template #trigger>
			<Button variant="subtle" icon-left="lucide-landmark" icon-right="lucide-chevrons-up-down">
				<span class="flex items-baseline gap-1.5">
					<span class="text-ink-gray-9">{{ selected?.account_name || __("Choose a bank account") }}</span>
					<span v-if="selected?.bank" class="text-ink-gray-5">{{ selected.bank }}</span>
				</span>
			</Button>
		</template>
	</Dropdown>
</template>
