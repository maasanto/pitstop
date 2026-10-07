<script setup>
import {
	Alert,
	Button,
	Dropdown,
	ErrorMessage,
	FrappeUIProvider,
	KeyboardShortcut,
	LoadingText,
	Popover,
	Skeleton,
	TabButtons,
	TextInput,
	call,
	dayjs,
	toast,
	useCall,
} from "frappe-ui";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import AutoReconciliationSettings from "./components/AutoReconciliationSettings.vue";
import BankAccountPicker from "./components/BankAccountPicker.vue";
import DocumentLookupDialog from "./components/DocumentLookupDialog.vue";
import DocumentTypeIcon from "./components/DocumentTypeIcon.vue";
import PairingRow from "./components/PairingRow.vue";
import PeriodPicker from "./components/PeriodPicker.vue";
import PreviewDialog from "./components/PreviewDialog.vue";
import ReconciledTab from "./components/ReconciledTab.vue";
import RuleDialog from "./components/RuleDialog.vue";
import RuleOffers from "./components/RuleOffers.vue";
import SearchDialog from "./components/SearchDialog.vue";
import { DOCUMENT_TYPES, descriptionText, formatDate, formatMoney, formatPercent } from "./format";
import { readStored, writeStored } from "./storage";
import { __, _n } from "./translation";

const period = ref([dayjs().subtract(89, "day").format("YYYY-MM-DD"), dayjs().format("YYYY-MM-DD")]);
const bankAccount = ref(null);
const tab = ref("proposals");
const showGuide = ref(!readStored("pitstop:guide-dismissed"));

const accounts = useCall({
	url: "/api/v2/method/pitstop.api.get_bank_accounts",
	onSuccess: (rows) => {
		const remembered = rows.find((account) => account.name === readStored("pitstop:bank-account"));
		bankAccount.value ||= (remembered || rows[0])?.name;
	},
});
const company = computed(
	() => (accounts.data || []).find((account) => account.name === bankAccount.value)?.company,
);
watch(bankAccount, (account) => account && writeStored("pitstop:bank-account", account));

// The proposal each line is paired with: the scorer's first not refused, unless the user picked another
const chosen = reactive({});
const refused = reactive({});
const approved = reactive(new Set());

// Lines arrive a page at a time, latest first: the first ones are there to review while Dokos scores the others
const pairings = reactive({ data: null, loading: false, error: null, scored: 0 });
let pairingsRequest = 0;

async function loadPairings() {
	const request = ++pairingsRequest;
	const previous = pairings.data?.pairings || [];
	const params = { bank_account: bankAccount.value, from_date: period.value[0], to_date: period.value[1] };
	const loaded = new Map();
	Object.assign(pairings, { loading: true, error: null, scored: 0 });
	focusedIndex.value = 0;
	try {
		let page;
		do {
			page = await call("pitstop.api.get_pairings", { ...params, start: pairings.scored });
			if (request !== pairingsRequest) return;
			pairings.scored += page.pairings.length;
			// A line reconciled meanwhile shifts the next page by one: the line seen twice is shown once
			page.pairings.forEach((pairing) => loaded.set(pairing.line.name, pairing));
			restoreReview(page.pairings);
			pairings.data = {
				total: page.total,
				truncated: page.truncated,
				rule_offers: page.rule_offers ?? pairings.data?.rule_offers ?? [],
				// Until a reload reaches them, the lines it has not scored yet keep their previous pairing
				pairings: [
					...loaded.values(),
					...previous.slice(loaded.size).filter((pairing) => !loaded.has(pairing.line.name)),
				],
			};
		} while (page.pairings.length && pairings.scored < page.total);
	} catch (error) {
		if (request === pairingsRequest) pairings.error = error;
	} finally {
		if (request === pairingsRequest) pairings.loading = false;
	}
}

watch([bankAccount, period], () => {
	if (!bankAccount.value || period.value.length !== 2) return;
	pairings.data = null;
	approved.clear();
	[chosen, refused].forEach((state) => Object.keys(state).forEach((name) => delete state[name]));
	loadPairings();
});
const lines = computed(() => pairings.data?.pairings || []);
const ruleOffers = computed(() => pairings.data?.rule_offers || []);

const filters = reactive({ direction: "all", text: "", min: "", max: "" });
const directionOptions = [
	{ label: __("All"), value: "all" },
	{ label: __("Money in"), value: "in" },
	{ label: __("Money out"), value: "out" },
];
// The same arrows as on each line's date, so the filter reads as "lines like these"
const DIRECTION_ICONS = {
	in: "lucide-arrow-down-left text-ink-green-7",
	out: "lucide-arrow-up-right text-ink-red-6",
};
const isFiltered = computed(
	() => filters.direction !== "all" || filters.text.trim() || filters.min !== "" || filters.max !== "",
);
// What the text matches: the line, and the documents it is paired with
function searchableText(pairing) {
	const documents = chosenFor(pairing)?.documents || [];
	return [
		descriptionText(pairing.line.description),
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
// No count until the lines are there: a zero while loading reads as nothing to do
const count = (rows) => (pairings.data ? ` · ${rows.length}` : "");
const tabOptions = computed(() => [
	{ label: `${__("Proposals")}${count(proposed.value)}`, value: "proposals" },
	{ label: `${__("Without proposal")}${count(unmatched.value)}`, value: "unmatched" },
	{ label: __("Already reconciled"), value: "reconciled" },
]);
const hasProposals = computed(() => lines.value.some((pairing) => chosenFor(pairing)));

function chosenFor(pairing) {
	const name = pairing.line.name;
	return chosen[name] || pairing.proposals.find((proposal) => !refused[name]?.includes(proposal.key));
}

function refuse(pairing) {
	const name = pairing.line.name;
	const proposal = chosenFor(pairing);
	refused[name] = [...(refused[name] || []), proposal.key];
	toast(__("Lead refused: {0}", [leadLabel(proposal)]), {
		duration: 10000,
		action: { label: __("Undo"), onClick: () => restoreLead(pairing, proposal.key) },
	});
	delete chosen[name];
	approved.delete(name);
	saveReview();
	saveRefusals(name);
	// The next lead may sit in another confidence section: follow the line there
	const index = ordered.value.indexOf(pairing);
	if (index !== -1) focusedIndex.value = index;
	moveFocus(0);
	openSearch(pairing);
}

function restoreLeads(pairing) {
	delete refused[pairing.line.name];
	saveRefusals(pairing.line.name);
}

function restoreLead(pairing, key) {
	const name = pairing.line.name;
	refused[name] = refused[name]?.filter((refusedKey) => refusedKey !== key);
	saveRefusals(name);
}

// Refusals live on the server, where they follow the line to every browser and teach the matcher. A line's
// saves are chained: two quick changes must land in the order they were made.
const refusalSaves = {};
function saveRefusals(name) {
	const proposals = [...(refused[name] || [])];
	refusalSaves[name] = (refusalSaves[name] || Promise.resolve())
		.then(() => call("pitstop.api.set_refused_proposals", { bank_transaction: name, proposals }))
		.catch((error) => toast.error(error.messages?.[0] || error.message));
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
	if (refused[name]?.includes(proposal.key)) {
		refused[name] = refused[name].filter((key) => key !== proposal.key);
		saveRefusals(name);
	}
	approved.add(name);
	saveReview();
}

function approveAll(section) {
	section.pairings.forEach((pairing) => approved.add(pairing.line.name));
	saveReview();
}

const storageKey = (kind) => `pitstop:${kind}:${bankAccount.value}`;

// Pre-approvals live in this browser only, until validated: a reload keeps them, a colleague does not see
// them. Lines outside the period on screen keep what was stored for them.
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
}

function restoreReview(pagePairings) {
	const saved = readStored(storageKey("approved")) || {};
	for (const pairing of pagePairings) {
		const name = pairing.line.name;
		delete chosen[name];
		delete refused[name];
		approved.delete(name);
		if (pairing.refused.length) refused[name] = [...pairing.refused];
		const proposal = pairing.proposals.find((candidate) => candidate.key === saved[name]);
		if (proposal) {
			chosen[name] = proposal;
			approved.add(name);
		}
	}
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
	url: "/api/v2/method/pitstop.api.reconcile_pairings",
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
		// A line that cleared a payment file's transit account stays reconciled
		const undoable = done.filter((result) => result.undoable);
		toast.success(_n(done.length, __("1 line reconciled"), __("{0} lines reconciled", [done.length])), {
			description: __("About {0} min of manual matching saved", [minutes]),
			duration: 20000,
			action: undoable.length ? { label: __("Undo"), onClick: () => undo(undoable, keys) } : undefined,
		});
	}
	done.forEach((result) => approved.delete(result.bank_transaction));
	saveReview();
	refresh();
}

const undoCall = useCall({
	url: "/api/v2/method/pitstop.api.undo_pairings",
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
	url: "/api/v2/method/pitstop.api.get_progress",
	immediate: false,
	params: () => ({ bank_account: bankAccount.value }),
});
watch(bankAccount, (account) => account && monthlyProgress.reload());
const periodTotals = useCall({
	url: "/api/v2/method/pitstop.api.get_period_totals",
	immediate: false,
	params: () => ({ bank_account: bankAccount.value, from_date: period.value[0], to_date: period.value[1] }),
});
watch([bankAccount, period], () => bankAccount.value && period.value.length === 2 && periodTotals.reload());
const DIRECTIONS = [
	{ key: "in", label: () => __("Money in"), icon: "lucide-arrow-down-left", tint: "text-ink-green-6" },
	{ key: "out", label: () => __("Money out"), icon: "lucide-arrow-up-right", tint: "text-ink-red-5" },
];
const reconciledShare = (direction) => (direction.total ? direction.reconciled / direction.total : 1);
const isComplete = (month) => month.lines && month.reconciled === month.lines;
// Consecutive past months fully reconciled; the current one counts once it is complete too
const streak = computed(() => {
	const months = monthlyProgress.data || [];
	const past = isComplete(months[0] || {}) ? months : months.slice(1);
	const firstGap = past.findIndex((month) => !isComplete(month));
	return firstGap === -1 ? past.length : firstGap;
});

function refresh() {
	loadPairings();
	monthlyProgress.reload();
	periodTotals.reload();
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

// The other way round, from a document; /pitstop?doctype=…&name=… opens it on that document
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
	];
}

// A line without a lead and a line whose leads were all refused call for different actions
const unmatchedGroups = computed(() =>
	[
		{
			key: "refused",
			title: () => __("Leads you refused"),
			hint: () => __("Dokos had a lead for these lines and you refused it. Restore it, or pick another document."),
			pairings: unmatched.value.filter((pairing) => pairing.proposals.length),
		},
		{
			key: "empty",
			title: () => __("Nothing convincing"),
			hint: () =>
				__("Dokos found nothing convincing for these lines. Search a document, or record what the money is."),
			pairings: unmatched.value.filter((pairing) => !pairing.proposals.length),
		},
	].filter((group) => group.pairings.length),
);

function leadLabel(proposal) {
	if (proposal.rule) return proposal.rule.rule_name;
	if (proposal.settlement) return __("{0} payments settled at once", [proposal.documents.length]);
	const [document] = proposal.documents;
	return [document.party_name || document.party, document.name].filter(Boolean).join(" · ");
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
	writeStored("pitstop:guide-dismissed", true);
}

// Keyboard review: the list is a queue the user walks through without the mouse
const focusedIndex = ref(0);
const focusedPairing = computed(() => ordered.value[focusedIndex.value]);
const SHORTCUTS = [
	{ combo: "ArrowDown", alternatives: ["J"], label: () => __("Next line") },
	{ combo: "ArrowUp", alternatives: ["K"], label: () => __("Previous line") },
	{ combo: "Space", label: () => __("Pre-approve or release") },
	{ combo: "P", label: () => __("Preview the document") },
	{ combo: "X", label: () => __("Refuse the lead") },
	{ combo: "O", alternatives: ["/"], label: () => __("Other leads, or another document") },
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
				<div class="mx-auto flex max-w-[1280px] flex-wrap items-center gap-3 px-4 pb-3 pt-7 sm:px-8">
					<h1 class="mr-4 text-4xl-semibold text-ink-gray-9">{{ __("Bank reconciliation") }}</h1>
					<BankAccountPicker v-model="bankAccount" :accounts="accounts.data || []" />
					<PeriodPicker v-model="period" :company="company" />
					<div class="ml-auto flex items-center gap-1">
						<span v-if="streak" class="mr-2 flex items-center gap-0.5 text-sm text-ink-amber-7">
							<span class="lucide-flame size-3.5" aria-hidden="true" />
							{{ _n(streak, __("1 month up to date"), __("{0} months up to date", [streak])) }}
						</span>
						<Popover v-if="periodTotals.data" align="end">
							<template #trigger>
								<button
									type="button"
									class="mr-2 flex items-center gap-4 rounded px-2 py-1 text-sm text-ink-gray-6 hover:bg-surface-gray-2"
								>
									<span v-for="direction in DIRECTIONS" :key="direction.key" class="flex items-center gap-1.5">
										<span :class="[direction.icon, direction.tint, 'size-3.5']" aria-hidden="true" />
										{{ direction.label() }}
										<span class="tabular-nums text-ink-gray-8">
											{{ formatMoney(periodTotals.data[direction.key].total, periodTotals.data.currency) }}
										</span>
										<span class="tabular-nums">
											· {{ formatPercent(reconciledShare(periodTotals.data[direction.key])) }}
										</span>
									</span>
								</button>
							</template>
							<div class="w-80 space-y-3 p-3">
								<p class="text-sm-medium text-ink-gray-9">{{ __("Reconciled over the period") }}</p>
								<div v-for="direction in DIRECTIONS" :key="direction.key" class="space-y-1.5">
									<div class="flex items-center justify-between text-sm text-ink-gray-7">
										<span class="flex items-center gap-1.5">
											<span :class="[direction.icon, direction.tint, 'size-3.5']" aria-hidden="true" />
											{{ direction.label() }}
										</span>
										<span class="tabular-nums text-ink-gray-9">
											{{ formatMoney(periodTotals.data[direction.key].total, periodTotals.data.currency) }}
										</span>
									</div>
									<div class="h-1.5 overflow-hidden rounded-full bg-surface-gray-3">
										<div
											class="h-full rounded-full bg-surface-green-6"
											:style="{ width: `${100 * reconciledShare(periodTotals.data[direction.key])}%` }"
										/>
									</div>
									<p class="text-xs text-ink-gray-6 tabular-nums">
										{{
											__("{0} reconciled · {1} left · {2} lines", [
												formatMoney(periodTotals.data[direction.key].reconciled, periodTotals.data.currency),
												formatMoney(
													periodTotals.data[direction.key].total - periodTotals.data[direction.key].reconciled,
													periodTotals.data.currency,
												),
												periodTotals.data[direction.key].lines,
											])
										}}
									</p>
								</div>
							</div>
						</Popover>
						<Popover align="end">
							<template #trigger>
								<Button
									variant="ghost"
									icon="lucide-keyboard"
									:label="__('Keyboard shortcuts')"
									:tooltip="__('Keyboard shortcuts')"
								/>
							</template>
							<div class="w-80 space-y-2 p-3">
								<p class="text-sm-medium text-ink-gray-9">{{ __("Review without the mouse") }}</p>
								<div
									v-for="shortcut in SHORTCUTS"
									:key="shortcut.combo"
									class="flex items-center justify-between gap-4 text-sm text-ink-gray-7"
								>
									{{ shortcut.label() }}
									<span class="flex shrink-0 items-center gap-1.5">
										<KeyboardShortcut :combo="shortcut.combo" :alt-combos="shortcut.alternatives" bg />
									</span>
								</div>
							</div>
						</Popover>
						<AutoReconciliationSettings />
						<Button
							variant="ghost"
							icon="lucide-external-link"
							:label="__('Open the classic page')"
							:tooltip="__('Open the classic page')"
							link="/app/bank-reconciliation"
						/>
					</div>
				</div>
				<nav class="mx-auto mt-2 flex max-w-[1280px] flex-wrap items-center justify-between gap-x-3 px-4 sm:px-8">
					<TabButtons v-model="tab" type="underline" :options="tabOptions" />
					<Button
						variant="ghost"
						icon-left="lucide-file-search"
						:label="__('Find the line of a document')"
						@click="lookup.open = true"
					/>
				</nav>
			</header>

			<main class="mx-auto max-w-[1280px] px-4 pt-8 sm:px-8">
				<ErrorMessage v-if="pairings.error" :message="pairings.error" class="mb-4" />
				<LoadingText
					v-if="tab !== 'reconciled' && pairings.loading"
					class="mb-4"
					:text="
						pairings.data
							? __('Pairing your bank lines: {0} of {1}', [pairings.scored, pairings.data.total])
							: __('Pairing your bank lines…')
					"
				/>
				<p v-if="pairings.data?.truncated" class="mb-4 text-p-sm text-ink-amber-7">
					{{ __("Only the latest lines of the period are shown: narrow the period to see the others.") }}
				</p>

				<Alert
					v-if="tab === 'proposals' && showGuide && hasProposals"
					class="mb-8"
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

				<div v-if="tab !== 'reconciled' && lines.length" class="mb-8 flex flex-wrap items-center gap-2">
					<TabButtons v-model="filters.direction" :options="directionOptions">
						<template #prefix="{ button }">
							<span
								v-if="DIRECTION_ICONS[button.modelValue]"
								:class="['size-4', DIRECTION_ICONS[button.modelValue]]"
								aria-hidden="true"
							/>
						</template>
					</TabButtons>
					<TextInput
						v-model="filters.text"
						class="w-64"
						:debounce="200"
						:placeholder="__('Label, party, number or amount')"
					>
						<template #prefix><span class="lucide-search size-4" aria-hidden="true" /></template>
					</TextInput>
					<div class="flex items-center gap-1.5" role="group" :aria-label="__('Amount')">
						<span class="pl-2 pr-0.5 text-sm text-ink-gray-5">{{ __("Amount") }}</span>
						<TextInput v-model="filters.min" class="w-24" type="number" min="0" :placeholder="__('Min')" />
						<span class="text-ink-gray-4" aria-hidden="true">–</span>
						<TextInput v-model="filters.max" class="w-24" type="number" min="0" :placeholder="__('Max')" />
					</div>
					<Button v-if="isFiltered" variant="ghost" :label="__('Clear filters')" @click="clearFilters" />
				</div>

				<ul
					v-if="tab !== 'unmatched'"
					class="mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-gray-6"
					:aria-label="__('Document types')"
				>
					<li v-for="doctype in Object.keys(DOCUMENT_TYPES)" :key="doctype" class="flex items-center gap-1.5">
						<DocumentTypeIcon :doctype="doctype" />
						{{ __(doctype) }}
					</li>
				</ul>

				<template v-if="tab === 'proposals'">
					<RuleOffers
						v-if="ruleOffers.length"
						:offers="ruleOffers"
						:bank-account="bankAccount"
						@answered="refresh"
					/>

					<div
						v-if="pairings.data && !pairings.loading && !proposed.length"
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
						<section v-for="section in sections" :key="section.level" class="mb-14">
							<div
								v-if="isFolded(section)"
								class="flex items-center gap-3 rounded-6 border border-outline-green-3 bg-surface-green-1 px-6 py-4"
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
							<div class="mb-4 flex flex-wrap items-end gap-3">
								<div>
									<h2 class="text-2xl-semibold text-ink-gray-9">
										{{ section.title() }}
										<span class="ml-1.5 text-lg text-ink-gray-4">{{ section.pairings.length }}</span>
									</h2>
									<p class="mt-2 text-p-base text-ink-gray-5">{{ section.hint() }}</p>
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
					<div v-if="pairings.loading" class="space-y-3" aria-hidden="true">
						<Skeleton v-for="index in proposed.length ? 2 : 4" :key="index" class="h-20 w-full rounded-6" />
					</div>
				</template>

				<template v-else-if="tab === 'unmatched'">
					<RuleOffers
						v-if="ruleOffers.length"
						:offers="ruleOffers"
						:bank-account="bankAccount"
						@answered="refresh"
					/>
					<section v-for="group in unmatchedGroups" :key="group.key" class="mb-14">
						<h2 class="text-2xl-semibold text-ink-gray-9">
							{{ group.title() }}
							<span class="ml-1.5 text-lg text-ink-gray-4">{{ group.pairings.length }}</span>
						</h2>
						<p class="mb-4 mt-2 text-p-base text-ink-gray-5">{{ group.hint() }}</p>
						<div class="divide-y divide-outline-gray-1 border-y border-outline-gray-1">
							<div
								v-for="pairing in group.pairings"
								:key="pairing.line.name"
								class="flex flex-wrap items-center gap-x-5 gap-y-2 py-4"
							>
								<div class="w-24 shrink-0 text-sm text-ink-gray-5">{{ formatDate(pairing.line.date) }}</div>
								<div class="min-w-0 flex-1 basis-60">
									<div class="truncate text-base-medium text-ink-gray-9">{{ descriptionText(pairing.line.description) }}</div>
									<div
										v-if="group.key === 'refused'"
										class="mt-1 flex items-center gap-1 text-sm text-ink-gray-5"
									>
										<span class="lucide-thumbs-down size-3.5 shrink-0" aria-hidden="true" />
										<span class="truncate">{{
											__("Refused: {0}", [leadLabel(pairing.proposals[0])])
										}}</span>
										<Button
											class="ml-1 shrink-0"
											variant="ghost"
											size="xs"
											icon-left="lucide-undo-2"
											:label="__('Restore')"
											@click="restoreLeads(pairing)"
										/>
									</div>
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
					</section>
					<p v-if="pairings.data && !pairings.loading && !unmatched.length" class="py-16 text-center text-p-sm text-ink-gray-4">
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
					<div class="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-surface-gray-3" aria-hidden="true">
						<div class="h-full rounded-full bg-surface-green-6 transition-all" :style="{ width: `${progress}%` }" />
					</div>
					<span class="text-base tabular-nums text-ink-gray-8">
						<b class="text-ink-gray-9">{{
							_n(
								toValidate.length,
								__("1 of {0} pre-approved", [lines.length]),
								__("{0} of {1} pre-approved", [toValidate.length, lines.length]),
							)
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
