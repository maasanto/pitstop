<script setup>
import { Button, LoadingText, TextInput, dialog, toast, useCall } from "frappe-ui";
import { computed, ref } from "vue";
import { DOCTYPE_ICONS, deskUrl, formatDate, formatMoney } from "../format";
import { __ } from "../translation";

const props = defineProps({
	bankAccount: { type: String, required: true },
	period: { type: Array, required: true },
});
const emit = defineEmits(["changed"]);

const lines = useCall({
	url: "/api/v2/method/bank_matching.api.get_reconciled_lines",
	params: () => ({ bank_account: props.bankAccount, from_date: props.period[0], to_date: props.period[1] }),
	refetch: true,
});
const query = ref("");
const shown = computed(() => {
	const text = query.value.trim().toLowerCase();
	return (lines.data || []).filter(
		({ line, documents }) =>
			!text ||
			[line.description, line.reference_number, ...documents.flatMap((d) => [d.payment_entry, d.party])].some(
				(value) =>
					String(value || "")
						.toLowerCase()
						.includes(text),
			),
	);
});

const unlink = useCall({
	url: "/api/v2/method/erpnext.accounts.doctype.bank_transaction.bank_transaction.unreconcile_transaction_entry",
	method: "POST",
	immediate: false,
});
const cancel = useCall({ url: "/api/v2/method/frappe.client.cancel", method: "POST", immediate: false });

function confirmUnlink(line, document) {
	dialog.confirm({
		title: __("Unlink {0}?", [document.payment_entry]),
		message: __("The bank line goes back to the lines to reconcile. {0} itself is kept.", [
			document.payment_entry,
		]),
		confirmLabel: __("Unlink"),
		cancelLabel: __("Back"),
		onConfirm: async () => {
			await unlink.submit({
				bank_transaction_id: line.name,
				voucher_type: document.payment_document,
				voucher_id: document.payment_entry,
			});
			if (unlink.error) throw unlink.error;
			done(__("{0} unlinked", [document.payment_entry]));
		},
	});
}

function confirmCancel(document) {
	dialog.danger({
		title: __("Cancel {0}?", [document.payment_entry]),
		message: __(
			"The payment is cancelled, the invoices it paid are open again and the bank line goes back to the lines to reconcile.",
		),
		confirmLabel: __("Cancel the payment"),
		cancelLabel: __("Back"),
		onConfirm: async () => {
			await cancel.submit({ doctype: document.payment_document, name: document.payment_entry });
			if (cancel.error) throw cancel.error;
			done(__("{0} cancelled", [document.payment_entry]));
		},
	});
}

function done(message) {
	toast.success(message);
	lines.reload();
	emit("changed");
}
</script>

<template>
	<div>
		<TextInput v-model="query" class="mb-3 max-w-sm" :placeholder="__('Search a label, document or party')">
			<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
		</TextInput>
		<LoadingText v-if="lines.loading && !lines.data" />
		<p v-else-if="!shown.length" class="py-16 text-center text-p-sm text-ink-gray-4">
			{{ __("No reconciled line over this period") }}
		</p>
		<div class="divide-y divide-outline-gray-1">
			<div
				v-for="{ line, documents } in shown"
				:key="line.name"
				class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-4 py-3"
			>
				<div class="min-w-0">
					<div class="text-sm text-ink-gray-5">{{ formatDate(line.date) }}</div>
					<div class="mt-1 truncate text-base text-ink-gray-9" :title="line.description">
						{{ line.description }}
					</div>
					<div class="mt-1 text-base-semibold tabular-nums text-ink-gray-9">
						{{ formatMoney(line.amount, line.currency) }}
					</div>
				</div>
				<div class="space-y-1.5">
					<div
						v-for="document in documents"
						:key="document.payment_entry"
						class="flex items-center gap-2 rounded-4 border border-outline-gray-1 bg-surface-gray-1 px-2.5 py-1.5"
					>
						<span
							:class="DOCTYPE_ICONS[document.payment_document]"
							class="size-4 text-ink-gray-6"
							aria-hidden="true"
						/>
						<a
							:href="deskUrl(document.payment_document, document.payment_entry)"
							target="_blank"
							class="text-base-medium text-ink-gray-9 hover:underline"
						>
							{{ document.payment_entry }}
						</a>
						<span class="truncate text-base text-ink-gray-7">{{ document.party }}</span>
						<span v-if="document.created_by_reconciliation" class="shrink-0 text-sm text-ink-blue-5">
							{{ __("created by the reconciliation") }}
						</span>
						<span class="ml-auto shrink-0 tabular-nums text-ink-gray-8">{{
							formatMoney(document.allocated_amount, line.currency)
						}}</span>
						<Button
							variant="ghost"
							icon-left="lucide-unlink"
							:label="__('Unlink')"
							@click="confirmUnlink(line, document)"
						/>
						<Button
							v-if="document.created_by_reconciliation"
							variant="ghost"
							theme="red"
							icon-left="lucide-undo-2"
							:label="__('Cancel the payment')"
							@click="confirmCancel(document)"
						/>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
