<script setup>
import { Button, Dropdown, Skeleton, TextInput, Tooltip, dialog, toast, useCall } from "frappe-ui";
import { computed, ref } from "vue";
import { DOCTYPE_ICONS, deskUrl, descriptionText, formatDate, formatMoney } from "../format";
import { __ } from "../translation";

const props = defineProps({
	bankAccount: { type: String, required: true },
	period: { type: Array, required: true },
});
const emit = defineEmits(["changed"]);

const lines = useCall({
	url: "/api/v2/method/pitstop.api.get_reconciled_lines",
	params: () => ({ bank_account: props.bankAccount, from_date: props.period[0], to_date: props.period[1] }),
	refetch: true,
});
const query = ref("");
const shown = computed(() => {
	const text = query.value.trim().toLowerCase();
	return (lines.data || []).filter(
		({ line, documents }) =>
			!text ||
			[
				descriptionText(line.description),
				line.reference_number,
				...documents.flatMap((d) => [d.payment_entry, d.party]),
			].some(
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

// The reconciliation creates payments for invoices and journal entries for bank rules
const isPayment = (document) => document.payment_document === "Payment Entry";
const cancelLabel = (document) => (isPayment(document) ? __("Cancel the payment") : __("Cancel the entry"));

function documentActions(line, document) {
	return [
		{ label: __("Unlink"), icon: "lucide-unlink", onClick: () => confirmUnlink(line, document) },
		document.created_by_reconciliation && {
			label: cancelLabel(document),
			icon: "lucide-ban",
			theme: "red",
			onClick: () => confirmCancel(document),
		},
	].filter(Boolean);
}

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
		message: isPayment(document)
			? __(
					"The payment is cancelled, the invoices it paid are open again and the bank line goes back to the lines to reconcile.",
				)
			: __("The entry is cancelled and the bank line goes back to the lines to reconcile."),
		confirmLabel: cancelLabel(document),
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
		<TextInput v-model="query" class="mb-6 max-w-sm" :placeholder="__('Search a label, document or party')">
			<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
		</TextInput>
		<div v-if="lines.loading && !lines.data" class="space-y-3">
			<Skeleton v-for="index in 4" :key="index" class="h-12 w-full rounded-4" />
		</div>
		<p v-else-if="!shown.length" class="py-16 text-center text-p-sm text-ink-gray-4">
			{{ __("No reconciled line over this period") }}
		</p>
		<div v-else class="divide-y divide-outline-gray-1 border-y border-outline-gray-1">
			<div
				v-for="{ line, documents } in shown"
				:key="line.name"
				class="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-5 gap-y-1 py-3 md:grid-cols-[6rem_minmax(0,1fr)_7rem_minmax(0,1.2fr)]"
			>
				<div class="col-span-2 flex min-h-7 items-center text-sm text-ink-gray-5 md:col-span-1">
					{{ formatDate(line.date) }}
				</div>
				<div class="flex min-h-7 min-w-0 items-center">
					<span class="truncate text-base-medium text-ink-gray-9" :title="descriptionText(line.description)">
						{{ descriptionText(line.description) }}
					</span>
				</div>
				<div class="flex min-h-7 items-center justify-end text-base-semibold tabular-nums text-ink-gray-9">
					{{ formatMoney(line.amount, line.currency) }}
				</div>
				<div class="col-span-2 min-w-0 md:col-span-1">
					<div v-for="document in documents" :key="document.payment_entry" class="flex items-center gap-2">
						<span
							:class="DOCTYPE_ICONS[document.payment_document]"
							class="size-4 shrink-0 text-ink-gray-5"
							aria-hidden="true"
						/>
						<a
							:href="deskUrl(document.payment_document, document.payment_entry)"
							target="_blank"
							class="shrink-0 whitespace-nowrap text-base text-ink-gray-8 hover:underline"
						>
							{{ document.payment_entry }}
						</a>
						<span v-if="document.party" class="truncate text-sm text-ink-gray-5">{{ document.party }}</span>
						<Tooltip v-if="document.created_by_reconciliation" :text="__('Created by the reconciliation')">
							<span
								class="lucide-circle-plus size-3.5 shrink-0 text-ink-blue-5"
								role="img"
								:aria-label="__('Created by the reconciliation')"
							/>
						</Tooltip>
						<span class="ml-auto shrink-0 pl-2 text-base tabular-nums text-ink-gray-7">
							{{ formatMoney(document.allocated_amount, line.currency) }}
						</span>
						<Dropdown align="end" :options="documentActions(line, document)">
							<template #trigger="{ open }">
								<Button variant="ghost" icon="lucide-ellipsis" :active="open" :label="__('More actions')" />
							</template>
						</Dropdown>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
