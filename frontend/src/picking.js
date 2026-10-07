import { computed, reactive } from "vue";

// Single documents picked to pay a line together: the reconciliation takes documents of one type
export function usePicking(line) {
	const picked = reactive(new Map());
	const pickedDoctype = computed(() => [...picked.values()][0]?.documents[0].doctype);
	const pickedTotal = computed(() =>
		[...picked.values()].reduce((sum, proposal) => sum + proposal.documents[0].amount, 0),
	);
	const pickedGap = computed(() =>
		line.value ? Math.round((Math.abs(line.value.amount) - pickedTotal.value) * 100) / 100 : 0,
	);

	function isPickable(proposal) {
		return !pickedDoctype.value || proposal.documents[0]?.doctype === pickedDoctype.value;
	}

	function setPick(proposal, isPicked) {
		isPicked ? picked.set(proposal.key, proposal) : picked.delete(proposal.key);
	}

	// One document is that document's proposal; several become one manual proposal
	function pickedProposal() {
		const proposals = [...picked.values()];
		if (proposals.length === 1) return proposals[0];
		return {
			key: `manual:${proposals.map((proposal) => proposal.key).join(",")}`,
			level: "high",
			score: null,
			documents: proposals.map((proposal) => proposal.documents[0]),
			creates_payment: proposals.some((proposal) => proposal.creates_payment),
		};
	}

	return { picked, pickedTotal, pickedGap, isPickable, setPick, pickedProposal };
}
