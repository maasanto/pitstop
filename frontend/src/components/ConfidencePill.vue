<script setup>
import { Badge, Tooltip } from "frappe-ui";
import { computed } from "vue";
import { formatPercent } from "../format";
import { __ } from "../translation";

const props = defineProps({ proposal: { type: Object, required: true } });

const LEVELS = {
	high: { label: () => __("High", [], "Confidence"), theme: "green" },
	medium: { label: () => __("Medium", [], "Confidence"), theme: "orange" },
	low: { label: () => __("Low", [], "Confidence"), theme: "gray" },
};
// What the user decided outranks how sure Dokos is
const level = computed(() => {
	if (props.proposal.manual) return { label: () => __("Your pick"), theme: "blue" };
	if (props.proposal.rule) return { label: () => __("Rule"), theme: "blue" };
	return LEVELS[props.proposal.level];
});
// A raw score reads as a probability it is not: it stays a detail for the curious
const tooltip = computed(() => {
	if (props.proposal.manual) return __("Chosen by you");
	if (props.proposal.rule) return __("From your bank rule {0}", [props.proposal.rule.rule_name]);
	if (props.proposal.score === null) return __("Grouped payments: no score of their own");
	return __("Score: {0}", [formatPercent(props.proposal.score)]);
});
</script>

<template>
	<Tooltip :text="tooltip">
		<Badge :theme="level.theme" variant="outline" :label="level.label()" class="shrink-0" />
	</Tooltip>
</template>
