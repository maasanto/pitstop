<script setup>
import { formatDate } from "../format";

defineProps({ date: { type: String, default: null } });
</script>

<!-- The bank line and its documents show their dates alike, so the two read as a pair -->
<template>
	<span v-if="date" class="inline-flex shrink-0 items-center gap-1 text-sm tabular-nums text-ink-gray-5">
		<span class="lucide-calendar size-3.5 shrink-0 text-ink-gray-4" aria-hidden="true" />
		{{ formatDate(date) }}
	</span>
</template>
