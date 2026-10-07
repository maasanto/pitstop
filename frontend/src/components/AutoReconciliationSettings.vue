<script setup>
import { Button, Popover, Switch, call, toast, useCall } from "frappe-ui";
import { ref } from "vue";
import { __ } from "../translation";

const setting = useCall({ url: "/api/v2/method/pitstop.auto_reconciliation.get_auto_reconciliation" });
const saving = ref(false);

async function setEnabled(enabled) {
	// Set, never toggle: a frappe-ui control may emit the same change twice
	if (saving.value || enabled === setting.data?.enabled) return;
	saving.value = true;
	try {
		await call("pitstop.auto_reconciliation.set_auto_reconciliation", { enabled });
		setting.reload();
		toast.success(enabled ? __("Lines are now reconciled every hour") : __("Hourly reconciliation stopped"));
	} catch (error) {
		toast.error(error.messages?.[0] || error.message);
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<Popover align="end">
		<template #trigger>
			<Button variant="ghost" icon="lucide-settings" :label="__('Settings')" :tooltip="__('Settings')" />
		</template>
		<div class="w-80 space-y-3 p-3">
			<Switch
				:model-value="setting.data?.enabled"
				:disabled="!setting.data?.can_change || saving"
				:label="__('Reconcile automatically every hour')"
				:description="
					__(
						'Runs the automatic reconciliation of the classic page on the open lines of the last 90 days: a line whose label names an invoice or a payment is reconciled with it.',
					)
				"
				@update:model-value="setEnabled"
			/>
			<p v-if="setting.data && !setting.data.can_change" class="text-p-sm text-ink-gray-5">
				{{ __("Only users who can edit the Accounts Settings can change this.") }}
			</p>
			<a href="/app/accounts-settings" class="block text-p-sm text-ink-gray-5 underline">
				{{ __("Also in the Accounts Settings") }}
			</a>
		</div>
	</Popover>
</template>
