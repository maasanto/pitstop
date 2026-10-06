<script setup>
import { Tooltip } from "frappe-ui";
import { computed } from "vue";

const props = defineProps({
	// The scorer's reasons about the value this hint sits next to
	reasons: { type: Array, default: () => [] },
	// Said when no reason backs the value; without it, an unbacked value shows no hint
	missing: { type: String, default: null },
});

const HINTS = {
	exact: { icon: "lucide-check", color: "bg-surface-green-7 text-ink-green-1" },
	approximate: { icon: "lucide-minus", color: "bg-surface-amber-7 text-ink-amber-1" },
	missing: { icon: "lucide-x", color: "bg-surface-red-2 text-ink-red-7" },
};
const state = computed(() => {
	if (!props.reasons.length) return props.missing && "missing";
	return props.reasons.some((reason) => reason.exact) ? "exact" : "approximate";
});
const description = computed(() =>
	props.reasons.length ? props.reasons.map((reason) => reason.description).join(" · ") : props.missing,
);
</script>

<template>
	<Tooltip v-if="state" :text="description">
		<span
			:class="HINTS[state].color"
			class="inline-flex size-4 shrink-0 items-center justify-center rounded-full"
			role="img"
			:aria-label="description"
		>
			<span :class="HINTS[state].icon" class="size-2.5" aria-hidden="true" />
		</span>
	</Tooltip>
</template>
