<script setup>
import { Badge } from "frappe-ui";
import { computed } from "vue";
import { __ } from "../translation";

const props = defineProps({ level: { type: String, required: true } });

const LEVELS = {
	high: { label: () => __("High", [], "Confidence"), theme: "green", icon: "lucide-signal-high" },
	medium: { label: () => __("Medium", [], "Confidence"), theme: "amber", icon: "lucide-signal-medium" },
	low: { label: () => __("Low", [], "Confidence"), theme: "gray", icon: "lucide-signal-low" },
};
const level = computed(() => LEVELS[props.level]);
</script>

<template>
	<Badge :theme="level.theme" variant="subtle" size="md" :label="level.label()">
		<template #prefix><span :class="level.icon" class="size-3.5" aria-hidden="true" /></template>
	</Badge>
</template>
