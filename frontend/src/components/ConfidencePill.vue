<script setup>
import { Badge, Tooltip } from "frappe-ui";
import { computed } from "vue";
import { __ } from "../translation";

const props = defineProps({ proposal: { type: Object, required: true } });

const LEVELS = {
	high: { label: () => __("High", [], "Confidence"), theme: "green", icon: "lucide-signal-high" },
	medium: { label: () => __("Medium", [], "Confidence"), theme: "orange", icon: "lucide-signal-medium" },
	low: { label: () => __("Low", [], "Confidence"), theme: "gray", icon: "lucide-signal-low" },
};
// What the user decided outranks how sure Dokos is
const level = computed(() => {
	if (props.proposal.manual) return { label: () => __("Your pick"), theme: "blue", icon: "lucide-user-check" };
	if (props.proposal.rule) return { label: () => __("Rule"), theme: "blue", icon: "lucide-wand-sparkles" };
	return LEVELS[props.proposal.level];
});
// A raw score reads as a probability it is not: it stays a detail for the curious
const tooltip = computed(() => {
	if (props.proposal.manual) return __("Chosen by you");
	if (props.proposal.rule) return __("From your bank rule {0}", [props.proposal.rule.rule_name]);
	if (props.proposal.score === null) return __("Grouped payments: no score of their own");
	return __("Score: {0}", [
		new Intl.NumberFormat(window.lang || "en", { style: "percent" }).format(props.proposal.score),
	]);
});
</script>

<template>
	<Tooltip :text="tooltip">
		<Badge :theme="level.theme" variant="outline" :label="level.label()" class="shrink-0">
			<template #prefix><span :class="level.icon" class="size-3" aria-hidden="true" /></template>
		</Badge>
	</Tooltip>
</template>
