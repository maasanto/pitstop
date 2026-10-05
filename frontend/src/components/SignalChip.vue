<script setup>
import { Tooltip } from "frappe-ui";
import { signalIcon } from "../format";

defineProps({ reason: { type: Object, required: true } });
</script>

<template>
	<Tooltip :text="reason.description">
		<span
			class="inline-flex size-5.5 shrink-0 items-center justify-center rounded-3"
			:class="reason.exact ? 'bg-surface-green-2 text-ink-green-7' : 'bg-surface-amber-2 text-ink-amber-7'"
			role="img"
			:aria-label="reason.description"
		>
			<span :class="signalIcon(reason)" class="size-3.5" aria-hidden="true" />
		</span>
	</Tooltip>
</template>
