<script setup>
import {
	Alert,
	Button,
	DateRangePicker,
	ErrorMessage,
	FrappeUIProvider,
	KeyboardShortcut,
	Popover,
	Select,
	Skeleton,
	TabButtons,
	toast,
	useCall,
} from "frappe-ui";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import PairingRow from "./components/PairingRow.vue";
import PreviewDialog from "./components/PreviewDialog.vue";
import ReconciledTab from "./components/ReconciledTab.vue";
import SearchDialog from "./components/SearchDialog.vue";
import { formatDate, formatMoney } from "./format";
import { readStored, writeStored } from "./storage";
import { __, _n } from "./translation";

const isoDate = (date) =>
	[date.getFullYear(), date.getMonth() + 1, date.getDate()]
		.map((part) => String(part).padStart(2, "0"))
		.join("-");
const today = new Date();
const period = ref([isoDate(new Date(today.getFullYear(), today.getMonth() - 2, 1)), isoDate(today)]);
// The system's date format, `dd-mm-yyyy` in Frappe's notation, is `DD-MM-YYYY` in dayjs'
const dateFormat = window.date_format?.toUpperCase();
const bankAccount = ref(null);
const tab = ref("proposals");
const showGuide = ref(!readStored("bank_matching:guide-dismissed"));

const accounts = useCall({
	url: "/api/v2/method/bank_matching.api.get_bank_accounts",
	onSuccess: (rows) => (bankAccount.value ||= rows[0]?.name),
});
const accountOptions = computed(() =>
	(accounts.data || []).map((account) => ({
		label: `${account.account_name} · ${account.bank}`,
		value: account.name,
	})),
);

const pairings = useCall({
	url: "/api/v2/method/bank_matching.api.get_pairings",
	immediate: false,
	params: () => ({ bank_account: bankAccount.value, from_date: period.value[0], to_date: period.value[1] }),
	onSuccess: restoreApprovals,
});
watch([bankAccount, period], () => bankAccount.value && period.value.length === 2 && pairings.reload());

// The proposal each line is paired with: the scorer's first, unless the user picked another
const chosen = reactive({});
const approved = reactive(new Set());
const lines = computed(() => pairings.data?.pairings || []);
const proposed = computed(() => lines.value.filter((pairing) => chosenFor(pairing)));
const unmatched = computed(() => lines.value.filter((pairing) => !chosenFor(pairing)));

const SECTIONS = [
	{
		level: "high",
		title: () => __("Ready to validate"),
		hint: () => __("Several signals agree and no other party comes close. A glance is enough."),
	},
	{
		level: "medium",
		title: () => __("To check"),
		hint: () => __("Likely right, but not certain. Compare with the other leads before approving."),
	},
	{
		level: "low",
		title: () => __("Uncertain"),
		hint: () => __("Only weak signals. Open the preview, or search the right document."),
	},
];
const sections = computed(() =>
	SECTIONS.map((section) => ({
		...section,
		pairings: proposed.value.filter((pairing) => chosenFor(pairing).level === section.level),
	})).filter((section) => section.pairings.length),
);
const ordered = computed(() => sections.value.flatMap((section) => section.pairings));
const tabOptions = computed(() => [
	{ label: `${__("Proposals")} · ${proposed.value.length}`, value: "proposals" },
	{ label: `${__("Without proposal")} · ${unmatched.value.length}`, value: "unmatched" },
	{ label: __("Already reconciled"), value: "reconciled" },
]);

function chosenFor(pairing) {
	return chosen[pairing.line.name] || pairing.proposals[0];
}

function toggle(pairing) {
	const name = pairing.line.name;
	approved.has(name) ? approved.delete(name) : approved.add(name);
	focusedIndex.value = Math.max(0, ordered.value.indexOf(pairing));
	saveApprovals();
}

function choose(pairing, proposal) {
	chosen[pairing.line.name] = proposal;
	approved.add(pairing.line.name);
	saveApprovals();
}

function approveAll(section) {
	section.pairings.forEach((pairing) => approved.add(pairing.line.name));
	saveApprovals();
}

const storageKey = () => `bank_matching:approved:${bankAccount.value}`;

// Pre-approvals live in this browser only, until validated: a reload keeps them, a colleague does not see them
function saveApprovals() {
	writeStored(
		storageKey(),
		Object.fromEntries(
			lines.value.filter((p) => approved.has(p.line.name)).map((p) => [p.line.name, chosenFor(p).key]),
		),
	);
}

function restoreApprovals(data) {
	approved.clear();
	Object.keys(chosen).forEach((name) => delete chosen[name]);
	const saved = readStored(storageKey()) || {};
	for (const pairing of data.pairings) {
		const proposal = pairing.proposals.find((candidate) => candidate.key === saved[pairing.line.name]);
		if (proposal) {
			chosen[pairing.line.name] = proposal;
			approved.add(pairing.line.name);
		}
	}
	focusedIndex.value = 0;
}

const toValidate = computed(() => lines.value.filter((pairing) => approved.has(pairing.line.name)));
const paymentsToCreate = computed(
	() => toValidate.value.filter((pairing) => chosenFor(pairing).creates_payment).length,
);
const totalToValidate = computed(() =>
	toValidate.value.reduce((sum, pairing) => sum + Math.abs(pairing.line.amount), 0),
);
const currency = computed(() => lines.value[0]?.line.currency);
const progress = computed(() =>
	lines.value.length ? Math.round((100 * toValidate.value.length) / lines.value.length) : 0,
);

const reconcile = useCall({
	url: "/api/v2/method/bank_matching.api.reconcile_pairings",
	method: "POST",
	immediate: false,
});

async function validate() {
	if (!toValidate.value.length || reconcile.loading) return;
	await reconcile.submit({
		pairings: toValidate.value.map((pairing) => ({
			bank_transaction: pairing.line.name,
			documents: chosenFor(pairing).documents.map(({ doctype, name }) => ({ doctype, name })),
		})),
	});
	if (reconcile.error) {
		toast.error(reconcile.error.message);
		return;
	}
	const failed = reconcile.data.filter((result) => result.error);
	const succeeded = reconcile.data.length - failed.length;
	if (succeeded)
		toast.success(_n(succeeded, __("1 line reconciled"), __("{0} lines reconciled", [succeeded])));
	failed.forEach((result) =>
		toast.error(result.error, { description: result.bank_transaction, duration: 15000 }),
	);
	reconcile.data
		.filter((result) => !result.error)
		.forEach((result) => approved.delete(result.bank_transaction));
	saveApprovals();
	pairings.reload();
}

const preview = reactive({ open: false, document: null });
function showPreview(document) {
	preview.document = document;
	preview.open = true;
}

const search = reactive({ open: false, pairing: null });
function openSearch(pairing) {
	search.pairing = pairing;
	search.open = true;
}

function newPaymentUrl(line) {
	const receive = line.amount > 0;
	const params = new URLSearchParams({
		payment_type: receive ? "Receive" : "Pay",
		party_type: receive ? "Customer" : "Supplier",
		posting_date: line.date,
		paid_amount: Math.abs(line.amount),
		received_amount: Math.abs(line.amount),
		reference_no: line.reference_number || line.name,
		reference_date: line.date,
		bank_account: bankAccount.value,
	});
	return `/app/payment-entry/new?${params}`;
}

function dismissGuide() {
	showGuide.value = false;
	writeStored("bank_matching:guide-dismissed", true);
}

// Keyboard review: the list is a queue the user walks through without the mouse
const focusedIndex = ref(0);
const rows = ref({});
const focusedPairing = computed(() => ordered.value[focusedIndex.value]);
const SHORTCUTS = [
	{ combo: "ArrowDown", label: () => __("Next line") },
	{ combo: "ArrowUp", label: () => __("Previous line") },
	{ combo: "Space", label: () => __("Pre-approve or release") },
	{ combo: "P", label: () => __("Preview the document") },
	{ combo: "O", label: () => __("Show the other leads") },
	{ combo: "Slash", label: () => __("Search another document") },
	{ combo: "Mod+Enter", label: () => __("Validate the pre-approved") },
];

function moveFocus(step) {
	focusedIndex.value = Math.min(Math.max(focusedIndex.value + step, 0), ordered.value.length - 1);
	nextTick(() =>
		document.getElementById(`line-${focusedPairing.value?.line.name}`)?.scrollIntoView({ block: "nearest" }),
	);
}

function onKeydown(event) {
	if (tab.value !== "proposals" || search.open || preview.open) return;
	if (event.target.closest?.("input, textarea, select, [contenteditable], [role=dialog]")) return;
	const pairing = focusedPairing.value;
	const handlers = {
		ArrowDown: () => moveFocus(1),
		j: () => moveFocus(1),
		ArrowUp: () => moveFocus(-1),
		k: () => moveFocus(-1),
		" ": () => pairing && toggle(pairing),
		p: () => pairing && showPreview(chosenFor(pairing).documents[0]),
		o: () => pairing && rows.value[pairing.line.name]?.toggleAlternatives(),
		"/": () => pairing && openSearch(pairing),
	};
	if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
		event.preventDefault();
		validate();
	} else if (handlers[event.key] && !event.metaKey && !event.ctrlKey && !event.altKey) {
		event.preventDefault();
		handlers[event.key]();
	}
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
	<FrappeUIProvider>
		<div class="min-h-screen bg-surface-base pb-32 text-ink-gray-8">
			<header class="border-b border-outline-gray-1">
				<div class="mx-auto flex max-w-[1200px] flex-wrap items-center gap-3 px-5 pb-1 pt-4">
					<h1 class="mr-2 text-2xl-semibold text-ink-gray-9">{{ __("Bank reconciliation") }}</h1>
					<Select
						v-model="bankAccount"
						class="w-64"
						:options="accountOptions"
						:placeholder="__('Bank account')"
					/>
					<DateRangePicker v-model="period" class="w-60" :clearable="false" :format="dateFormat" />
					<div class="ml-auto flex items-center gap-1">
						<Popover align="end">
							<template #trigger>
								<Button variant="ghost" icon="lucide-keyboard" :tooltip="__('Keyboard shortcuts')" />
							</template>
							<div class="w-72 space-y-2 p-3">
								<p class="text-sm-medium text-ink-gray-9">{{ __("Review without the mouse") }}</p>
								<div
									v-for="shortcut in SHORTCUTS"
									:key="shortcut.combo"
									class="flex items-center justify-between text-sm text-ink-gray-7"
								>
									{{ shortcut.label() }}
									<KeyboardShortcut :combo="shortcut.combo" />
								</div>
							</div>
						</Popover>
						<Button
							variant="ghost"
							icon="lucide-external-link"
							:tooltip="__('Open the classic page')"
							link="/app/bank-reconciliation"
						/>
					</div>
				</div>
				<nav class="mx-auto max-w-[1200px] px-5">
					<TabButtons v-model="tab" type="underline" :options="tabOptions" />
				</nav>
			</header>

			<main class="mx-auto max-w-[1200px] px-5 pt-5">
				<ErrorMessage v-if="pairings.error" :message="pairings.error" class="mb-4" />
				<p v-if="pairings.data?.truncated" class="mb-4 text-p-sm text-ink-amber-7">
					{{ __("Only the latest lines of the period are shown: narrow the period to see the others.") }}
				</p>

				<template v-if="tab === 'proposals'">
					<Alert
						v-if="showGuide"
						class="mb-5"
						theme="blue"
						:title="__('Dokos already paired your bank lines')"
						:description="
							__(
								'1. Check each pairing: the icons say what matched. 2. Click a line to pre-approve it. 3. Validate them all at once; invoices get their payment created.',
							)
						"
						dismissible
						@dismiss="dismissGuide"
					/>

					<div v-if="pairings.loading && !pairings.data" class="space-y-2">
						<Skeleton v-for="index in 4" :key="index" class="h-20 w-full rounded-6" />
					</div>

					<div
						v-else-if="pairings.data && !proposed.length"
						class="flex flex-col items-center gap-3 py-20 text-center"
					>
						<div class="rounded-full bg-surface-green-2 p-3 text-ink-green-7">
							<span class="lucide-circle-check size-6" aria-hidden="true" />
						</div>
						<p class="text-base text-ink-gray-8">{{ __("Nothing left to review over this period") }}</p>
						<p v-if="unmatched.length" class="text-sm text-ink-gray-5">
							{{
								_n(
									unmatched.length,
									__("1 line still needs a document of your choice."),
									__("{0} lines still need a document of your choice.", [unmatched.length]),
								)
							}}
						</p>
						<Button
							v-if="unmatched.length"
							:label="__('See the lines without proposal')"
							@click="tab = 'unmatched'"
						/>
					</div>

					<template v-else>
						<div class="mb-6 flex items-center gap-3">
							<div class="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-gray-2">
								<div
									class="h-full rounded-full bg-surface-green-6 transition-all"
									:style="{ width: `${progress}%` }"
								/>
							</div>
							<span class="shrink-0 text-sm tabular-nums text-ink-gray-6">
								{{ __("Pre-approved: {0} of {1}", [toValidate.length, lines.length]) }}
							</span>
						</div>

						<section v-for="section in sections" :key="section.level" class="mb-8">
							<div class="mb-2.5 flex items-end gap-3">
								<div>
									<h2 class="text-lg-semibold text-ink-gray-9">
										{{ section.title() }}
										<span class="ml-1 text-base text-ink-gray-5">{{ section.pairings.length }}</span>
									</h2>
									<p class="mt-0.5 text-p-sm text-ink-gray-5">{{ section.hint() }}</p>
								</div>
								<Button
									v-if="section.level === 'high'"
									class="ml-auto"
									variant="subtle"
									theme="green"
									icon-left="lucide-check-check"
									:label="__('Pre-approve these {0}', [section.pairings.length])"
									:disabled="section.pairings.every((pairing) => approved.has(pairing.line.name))"
									@click="approveAll(section)"
								/>
							</div>
							<div class="space-y-1.5">
								<PairingRow
									v-for="pairing in section.pairings"
									:id="`line-${pairing.line.name}`"
									:key="pairing.line.name"
									:ref="(row) => (rows[pairing.line.name] = row)"
									:pairing="pairing"
									:chosen="chosenFor(pairing)"
									:approved="approved.has(pairing.line.name)"
									:focused="focusedPairing === pairing"
									@toggle="toggle(pairing)"
									@choose="choose(pairing, $event)"
									@search="openSearch(pairing)"
									@preview="showPreview"
								/>
							</div>
						</section>
					</template>
				</template>

				<template v-else-if="tab === 'unmatched'">
					<p class="mb-3 text-p-sm text-ink-gray-5">
						{{
							__(
								"Dokos found nothing convincing for these lines. Search a document, or record what the money is.",
							)
						}}
					</p>
					<div class="divide-y divide-outline-gray-1">
						<div v-for="pairing in unmatched" :key="pairing.line.name" class="flex items-center gap-4 py-3">
							<div class="w-24 shrink-0 text-sm text-ink-gray-5">{{ formatDate(pairing.line.date) }}</div>
							<div class="min-w-0 flex-1 truncate text-base text-ink-gray-9">
								{{ pairing.line.description }}
							</div>
							<div class="w-28 shrink-0 text-right text-base-semibold tabular-nums text-ink-gray-9">
								{{ formatMoney(pairing.line.amount, pairing.line.currency) }}
							</div>
							<Button
								icon-left="lucide-search"
								:label="__('Search a document')"
								@click="openSearch(pairing)"
							/>
							<Button
								variant="ghost"
								icon-left="lucide-plus"
								:label="__('Create a payment')"
								:link="newPaymentUrl(pairing.line)"
							/>
						</div>
					</div>
					<p v-if="pairings.data && !unmatched.length" class="py-16 text-center text-p-sm text-ink-gray-4">
						{{ __("Every line has a proposal") }}
					</p>
				</template>

				<ReconciledTab
					v-else-if="bankAccount && period.length === 2"
					:bank-account="bankAccount"
					:period="period"
					@changed="pairings.reload()"
				/>
			</main>

			<Transition
				enter-from-class="translate-y-4 opacity-0"
				leave-to-class="translate-y-4 opacity-0"
				enter-active-class="transition duration-200"
				leave-active-class="transition duration-150"
			>
				<div
					v-if="tab !== 'reconciled' && toValidate.length"
					class="fixed inset-x-0 bottom-5 z-10 mx-auto flex w-fit max-w-[calc(100%-2.5rem)] items-center gap-4 rounded-7 border border-outline-gray-2 bg-surface-elevation-2 py-2 pl-5 pr-2 shadow-2xl"
					role="region"
					:aria-label="__('Pre-approved pairings')"
				>
					<span class="text-base text-ink-gray-8">
						<b class="text-ink-gray-9">{{
							_n(toValidate.length, __("1 pre-approved"), __("{0} pre-approved", [toValidate.length]))
						}}</b>
						· {{ formatMoney(totalToValidate, currency) }}
						<template v-if="paymentsToCreate">
							·
							{{
								_n(
									paymentsToCreate,
									__("1 payment will be created"),
									__("{0} payments will be created", [paymentsToCreate]),
								)
							}}
						</template>
					</span>
					<Button
						variant="ghost"
						:label="__('Clear selection')"
						@click="
							approved.clear();
							saveApprovals();
						"
					/>
					<Button
						variant="solid"
						size="md"
						icon-left="lucide-check-check"
						:label="
							_n(
								toValidate.length,
								__('Validate 1 reconciliation'),
								__('Validate {0} reconciliations', [toValidate.length]),
							)
						"
						:loading="reconcile.loading"
						@click="validate"
					/>
					<KeyboardShortcut combo="Mod+Enter" class="mr-2" />
				</div>
			</Transition>
		</div>

		<PreviewDialog v-model:open="preview.open" :document="preview.document" />
		<SearchDialog
			v-model:open="search.open"
			:line="search.pairing?.line"
			@choose="choose(search.pairing, $event)"
			@preview="showPreview"
		/>
	</FrappeUIProvider>
</template>
