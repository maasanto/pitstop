<script setup>
import { Button, Popover } from "frappe-ui";
import { computed, ref } from "vue";
import { __ } from "../translation";

const account = defineModel({ type: String, default: null });
const props = defineProps({ accounts: { type: Array, required: true } });

const isOpen = ref(false);
const selected = computed(() => props.accounts.find((candidate) => candidate.name === account.value));

function choose(candidate) {
	account.value = candidate.name;
	isOpen.value = false;
}
</script>

<template>
	<Popover v-model:open="isOpen" align="start">
		<template #trigger>
			<Button variant="subtle" icon-left="lucide-landmark" icon-right="lucide-chevrons-up-down">
				<span class="flex items-baseline gap-1.5">
					<span class="text-ink-gray-9">{{ selected?.account_name || __("Choose a bank account") }}</span>
					<span v-if="selected?.bank" class="text-ink-gray-5">{{ selected.bank }}</span>
				</span>
			</Button>
		</template>
		<div class="w-80 p-1.5">
			<p class="px-2.5 pb-1 pt-1.5 text-sm text-ink-gray-5">{{ __("Bank accounts") }}</p>
			<button
				v-for="candidate in accounts"
				:key="candidate.name"
				type="button"
				class="flex w-full items-center gap-3 rounded px-2.5 py-2 text-left hover:bg-surface-gray-2 focus-visible:bg-surface-gray-3 focus-visible:outline-none"
				@click="choose(candidate)"
			>
				<span class="lucide-landmark size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
				<span class="min-w-0 flex-1">
					<span class="block truncate text-base-medium text-ink-gray-9">{{ candidate.account_name }}</span>
					<span class="block truncate text-sm text-ink-gray-5">{{ candidate.account }}</span>
				</span>
				<span
					v-if="candidate.name === account"
					class="lucide-check size-4 shrink-0 text-ink-gray-9"
					:aria-label="__('Selected')"
				/>
			</button>
		</div>
	</Popover>
</template>
