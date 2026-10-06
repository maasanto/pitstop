<script setup>
import {
	Alert,
	Button,
	DateRangePicker,
	Dropdown,
	ErrorMessage,
	FrappeUIProvider,
	KeyboardShortcut,
	Popover,
	Select,
	Skeleton,
	TabButtons,
	TextInput,
	Tooltip,
	toast,
	useCall,
} from "frappe-ui";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import DocumentLookupDialog from "./components/DocumentLookupDialog.vue";
import PairingRow from "./components/PairingRow.vue";
import PreviewDialog from "./components/PreviewDialog.vue";
import ReconciledTab from "./components/ReconciledTab.vue";
import RuleDialog from "./components/RuleDialog.vue";
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
	onSuccess: restoreReview,
});
watch([bankAccount, period], () => bankAccount.value && period.value.length === 2 && pairings.reload());

// The proposal each line is paired with: the scorer's first not refused, unless the user picked another
const chosen = reactive({});
const refused = reactive({});
const approved = reactive(new Set());
const lines = computed(() => pairings.data?.pairings || []);

const filters = reactive({ direction: "all", text: "", min: "", max: "" });
const directionOptions = [
	{ label: __("All"), value: "all" },
	{ label: __("Money in"), value: "in" },
	{ label: __("Money out"), value: "out" },
];
const isFiltered = computed(
	() => filters.direction !== "all" || filters.text.trim() || filters.min !== "" || filters.max !== "",
);
// What the text matches: the line, and the documents it is paired with
function searchableText(pairing) {
	const documents = chosenFor(pairing)?.documents || [];
	return [
		pairing.line.description,
		pairing.line.bank_party_name,
		Math.abs(pairing.line.amount).toFixed(2),
		...documents.flatMap((document) => [document.name, document.party_name, document.reference]),
	]
		.join(" ")
		.toLowerCase();
}
function isShown(pairing) {
	const amount = Math.abs(pairing.line.amount);
	if (filters.direction === "in" && pairing.line.amount < 0) return false;
	if (filters.direction === "out" && pairing.line.amount > 0) return false;
	if (filters.min !== "" && amount < Number(filters.min)) return false;
	if (filters.max !== "" && amount > Number(filters.max)) return false;
	const text = filters.text.trim().toLowerCase();
	return !text || searchableText(pairing).includes(text.replace(",", "."));
}
function clearFilters() {
	Object.assign(filters, { direction: "all", text: "", min: "", max: "" });
}

const shown = computed(() => lines.value.filter(isShown));
const proposed = computed(() => shown.value.filter((pairing) => chosenFor(pairing)));
const unmatched = computed(() => shown.value.filter((pairing) => !chosenFor(pairing)));

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
	const name = pairing.line.name;
	return chosen[name] || pairing.proposals.find((proposal) => !refused[name]?.includes(proposal.key));
}

function refuse(pairing) {
	const name = pairing.line.name;
	refused[name] = [...(refused[name] || []), chosenFor(pairing).key];
	delete chosen[name];
	approved.delete(name);
	saveReview();
	// The next lead may sit in another confidence section: follow the line there
	const index = ordered.value.indexOf(pairing);
	if (index !== -1) focusedIndex.value = index;
	moveFocus(0);
	openSearch(pairing);
}

function restoreLeads(pairing) {
	delete refused[pairing.line.name];
	saveReview();
}

function toggle(pairing) {
	const name = pairing.line.name;
	approved.has(name) ? approved.delete(name) : approved.add(name);
	focusedIndex.value = Math.max(0, ordered.value.indexOf(pairing));
	saveReview();
}

function choose(pairing, proposal) {
	const name = pairing.line.name;
	const isLead = pairing.proposals.some((lead) => lead.key === proposal.key);
	// A document the user searched or grouped is ready by their own decision
	chosen[name] = isLead ? proposal : { ...proposal, level: "high", manual: true };
	refused[name] = refused[name]?.filter((key) => key !== proposal.key);
	approved.add(name);
	saveReview();
}

function approveAll(section) {
	section.pairings.forEach((pairing) => approved.add(pairing.line.name));
	saveReview();
}

const storageKey = (kind) => `bank_matching:${kind}:${bankAccount.value}`;

// The review lives in this browser only, until validated: a reload keeps it, a colleague does not see it.
// Lines outside the period on screen keep what was stored for them.
function storeForLines(kind, entries) {
	const stored = readStored(storageKey(kind)) || {};
	lines.value.forEach((pairing) => delete stored[pairing.line.name]);
	writeStored(storageKey(kind), { ...stored, ...entries });
}

function saveReview() {
	storeForLines(
		"approved",
		Object.fromEntries(
			lines.value.filter((p) => approved.has(p.line.name)).map((p) => [p.line.name, chosenFor(p).key]),
		),
	);
	storeForLines(
		"refused",
		Object.fromEntries(Object.entries(refused).filter(([, keys]) => keys?.length)),
	);
}

function restoreReview(data) {
	approved.clear();
	[chosen, refused].forEach((state) => Object.keys(state).forEach((name) => delete state[name]));
	Object.assign(refused, readStored(storageKey("refused")));
	const saved = readStored(storageKey("approved")) || {};
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

function asPayload(pairing) {
	const proposal = chosenFor(pairing);
	return proposal.rule
		? { bank_transaction: pairing.line.name, rule: proposal.rule.name }
		: {
				bank_transaction: pairing.line.name,
				documents: proposal.documents.map(({ doctype, name }) => ({ doctype, name })),
			};
}

// ponytail: a rough average of how long matching one line by hand takes, for the toast only
const MANUAL_SECONDS_PER_LINE = 45;

async function validate() {
	if (!toValidate.value.length || reconcile.loading) return;
	const keys = Object.fromEntries(toValidate.value.map((p) => [p.line.name, chosenFor(p).key]));
	await reconcile.submit({ pairings: toValidate.value.map(asPayload) });
	if (reconcile.error) {
		toast.error(reconcile.error.message);
		return;
	}
	const done = reconcile.data.filter((result) => !result.error);
	reconcile.data
		.filter((result) => result.error)
		.forEach((result) => toast.error(result.error, { description: result.bank_transaction, duration: 15000 }));
	if (done.length) {
		const minutes = Math.max(1, Math.round((done.length * MANUAL_SECONDS_PER_LINE) / 60));
		toast.success(_n(done.length, __("1 line reconciled"), __("{0} lines reconciled", [done.length])), {
			description: __("About {0} min of manual matching saved", [minutes]),
			duration: 20000,
			action: { label: __("Undo"), onClick: () => undo(done, keys) },
		});
	}
	done.forEach((result) => approved.delete(result.bank_transaction));
	saveReview();
	refresh();
}

const undoCall = useCall({
	url: "/api/v2/method/bank_matching.api.undo_pairings",
	method: "POST",
	immediate: false,
});

// Back to before the validation: lines unlinked, created vouchers cancelled, pairings pre-approved again
async function undo(results, keys) {
	await undoCall.submit({
		pairings: results.map(({ bank_transaction, created }) => ({ bank_transaction, created })),
	});
	if (undoCall.error) {
		toast.error(undoCall.error.message);
		return;
	}
	const undone = undoCall.data.filter((result) => !result.error).map((result) => result.bank_transaction);
	undoCall.data
		.filter((result) => result.error)
		.forEach((result) => toast.error(result.error, { description: result.bank_transaction }));
	const stored = readStored(storageKey("approved")) || {};
	undone.forEach((name) => (stored[name] = keys[name]));
	writeStored(storageKey("approved"), stored);
	toast.info(_n(undone.length, __("1 line put back"), __("{0} lines put back", [undone.length])));
	refresh();
}

const monthlyProgress = useCall({
	url: "/api/v2/method/bank_matching.api.get_progress",
	immediate: false,
	params: () => ({ bank_account: bankAccount.value }),
});
watch(bankAccount, (account) => account && monthlyProgress.reload());
const thisMonth = computed(() => monthlyProgress.data?.[0]);
const isComplete = (month) => month.lines && month.reconciled === month.lines;
// Consecutive past months fully reconciled; the current one counts once it is complete too
const streak = computed(() => {
	const months = monthlyProgress.data || [];
	const past = isComplete(months[0] || {}) ? months : months.slice(1);
	const firstGap = past.findIndex((month) => !isComplete(month));
	return firstGap === -1 ? past.length : firstGap;
});
const monthLabel = (month) =>
	new Intl.DateTimeFormat(window.lang || "en", { month: "long" }).format(new Date(`${month}-01`));

function refresh() {
	pairings.reload();
	monthlyProgress.reload();
}

// A section whose pairings are all pre-approved folds into one line, unless the user reopens it
const reopened = reactive(new Set());
const isFolded = (section) =>
	!reopened.has(section.level) && section.pairings.every((pairing) => approved.has(pairing.line.name));

const preview = reactive({ open: false, document: null });
function showPreview(document) {
	preview.document = document;
	preview.open = true;
}

const rule = reactive({ open: false, line: null });
function openRule(pairing) {
	rule.line = pairing.line;
	rule.open = true;
}

// The other way round, from a document; /bank-matching?doctype=…&name=… opens it on that document
const urlParams = new URLSearchParams(window.location.search);
const lookup = reactive({ open: false, doctype: urlParams.get("doctype"), name: urlParams.get("name") });
// The dialog animates in only from closed, so it opens once the page is there
onMounted(() => (lookup.open = Boolean(lookup.doctype && lookup.name)));
// Opened from the header afterwards, it starts with a search
watch(
	() => lookup.open,
	(isOpen) => isOpen || Object.assign(lookup, { doctype: null, name: null }),
);

const search = reactive({ open: false, pairing: null });
function openSearch(pairing) {
	search.pairing = pairing;
	search.open = true;
}

function unmatchedActions(pairing) {
	return [
		{
			label: __("Always book such lines…"),
			icon: "lucide-wand-sparkles",
			onClick: () => openRule(pairing),
		},
		{
			label: __("Create a payment"),
			icon: "lucide-plus",
			onClick: () => window.open(newPaymentUrl(pairing.line), "_blank"),
		},
		refused[pairing.line.name]?.length && {
			label: __("Restore the refused leads"),
			icon: "lucide-undo-2",
			onClick: () => restoreLeads(pairing),
		},
	].filter(Boolean);
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
const focusedPairing = computed(() => ordered.value[focusedIndex.value]);
const SHORTCUTS = [
	{ combo: "ArrowDown", label: () => __("Next line") },
	{ combo: "ArrowUp", label: () => __("Previous line") },
	{ combo: "Space", label: () => __("Pre-approve or release") },
	{ combo: "P", label: () => __("Preview the document") },
	{ combo: "X", label: () => __("Refuse the lead") },
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
		x: () => pairing && refuse(pairing),
		o: () => pairing && openSearch(pairing),
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
						<Tooltip
							v-if="thisMonth?.lines"
							:text="__('{0} of {1} lines reconciled', [thisMonth.reconciled, thisMonth.lines])"
						>
							<div class="mr-3 flex items-center gap-2 text-sm text-ink-gray-6">
								<svg viewBox="0 0 20 20" class="size-5 -rotate-90" aria-hidden="true">
									<circle cx="10" cy="10" r="8" fill="none" stroke-width="3" class="stroke-outline-gray-2" />
									<circle
										cx="10"
										cy="10"
										r="8"
										fill="none"
										stroke-width="3"
										stroke-linecap="round"
										class="stroke-ink-green-6 transition-all"
										:stroke-dasharray="`${(50.27 * thisMonth.reconciled) / thisMonth.lines} 50.27`"
									/>
								</svg>
								<span class="tabular-nums">
									{{ monthLabel(thisMonth.month) }} ·
									{{ Math.round((100 * thisMonth.reconciled) / thisMonth.lines) }} %
								</span>
								<span v-if="streak" class="flex items-center gap-0.5 text-ink-amber-7">
									<span class="lucide-flame size-3.5" aria-hidden="true" />
									{{ _n(streak, __("1 month up to date"), __("{0} months up to date", [streak])) }}
								</span>
							</div>
						</Tooltip>
						<Button
							variant="ghost"
							icon="lucide-file-search"
							:label="__('Find the line of a document')"
							:tooltip="__('Find the line of a document')"
							@click="lookup.open = true"
						/>
						<Popover align="end">
							<template #trigger>
								<Button
									variant="ghost"
									icon="lucide-keyboard"
									:label="__('Keyboard shortcuts')"
									:tooltip="__('Keyboard shortcuts')"
								/>
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
							:label="__('Open the classic page')"
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

				<div v-if="tab !== 'reconciled' && lines.length" class="mb-5 flex flex-wrap items-center gap-2">
					<TabButtons v-model="filters.direction" :options="directionOptions" />
					<TextInput
						v-model="filters.text"
						class="w-64"
						:debounce="200"
						:placeholder="__('Label, party, number or amount')"
					>
						<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
					</TextInput>
					<TextInput v-model="filters.min" class="w-24" type="number" min="0" :placeholder="__('Min')" />
					<TextInput v-model="filters.max" class="w-24" type="number" min="0" :placeholder="__('Max')" />
					<Button v-if="isFiltered" variant="ghost" :label="__('Clear filters')" @click="clearFilters" />
				</div>

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
						<template v-if="isFiltered">
							<p class="text-base text-ink-gray-8">{{ __("No proposal matches these filters") }}</p>
							<Button :label="__('Clear filters')" @click="clearFilters" />
						</template>
						<template v-else>
							<div class="rounded-full bg-surface-green-2 p-3 text-ink-green-7">
								<span class="lucide-party-popper size-6" aria-hidden="true" />
							</div>
							<p class="text-lg-semibold text-ink-gray-9">
								{{
									unmatched.length
										? __("Nothing left to review over this period")
										: __("Everything is reconciled over this period")
								}}
							</p>
							<p v-if="streak" class="flex items-center gap-1 text-sm text-ink-amber-7">
								<span class="lucide-flame size-4" aria-hidden="true" />
								{{ _n(streak, __("1 month up to date in a row"), __("{0} months up to date in a row", [streak])) }}
							</p>
						</template>
						<p v-if="!isFiltered && unmatched.length" class="text-sm text-ink-gray-5">
							{{
								_n(
									unmatched.length,
									__("1 line still needs a document of your choice."),
									__("{0} lines still need a document of your choice.", [unmatched.length]),
								)
							}}
						</p>
						<Button
							v-if="!isFiltered && unmatched.length"
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
							<div
								v-if="isFolded(section)"
								class="flex items-center gap-3 rounded-6 border border-outline-green-3 bg-surface-green-1 px-4 py-3"
							>
								<span class="lucide-circle-check size-5 text-ink-green-6" aria-hidden="true" />
								<span class="text-base-medium text-ink-gray-9">{{ section.title() }}</span>
								<span class="text-base text-ink-gray-6">
									{{
										_n(
											section.pairings.length,
											__("1 pairing, pre-approved"),
											__("{0} pairings, all pre-approved", [section.pairings.length]),
										)
									}}
								</span>
								<Button
									class="ml-auto"
									variant="ghost"
									:label="__('Show')"
									@click="reopened.add(section.level)"
								/>
							</div>
							<template v-else>
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
							<div class="space-y-2">
								<PairingRow
									v-for="pairing in section.pairings"
									:id="`line-${pairing.line.name}`"
									:key="pairing.line.name"
									:pairing="pairing"
									:chosen="chosenFor(pairing)"
									:approved="approved.has(pairing.line.name)"
									:focused="focusedPairing === pairing"
									@toggle="toggle(pairing)"
									@refuse="refuse(pairing)"
									@search="openSearch(pairing)"
									@preview="showPreview"
									@create-rule="openRule(pairing)"
								/>
							</div>
							</template>
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
							<Dropdown align="end" :options="unmatchedActions(pairing)">
								<template #trigger="{ open }">
									<Button
										variant="ghost"
										icon="lucide-ellipsis"
										:active="open"
										:label="__('More actions')"
									/>
								</template>
							</Dropdown>
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
					@changed="refresh"
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
							saveReview();
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
			:leads="search.pairing?.proposals"
			:current-key="search.pairing && chosenFor(search.pairing)?.key"
			:refused="refused[search.pairing?.line.name] || []"
			@choose="choose(search.pairing, $event)"
			@preview="showPreview"
		/>
		<RuleDialog v-model:open="rule.open" :line="rule.line" @created="refresh" />
		<DocumentLookupDialog
			v-model:open="lookup.open"
			:doctype="lookup.doctype"
			:name="lookup.name"
			@reconciled="refresh"
		/>
	</FrappeUIProvider>
</template>
