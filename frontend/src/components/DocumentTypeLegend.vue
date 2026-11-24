<script setup>
import { computed } from "vue";
import { DOCUMENT_TYPES } from "../format";
import DocumentTypeIcon from "./DocumentTypeIcon.vue";

const props = defineProps({
	// The types on screen, in any order and repeated: the legend explains only the icons the user can see
	doctypes: { type: Array, required: true },
});

const shown = computed(() => Object.keys(DOCUMENT_TYPES).filter((doctype) => props.doctypes.includes(doctype)));
</script>

<template>
	<ul
		v-if="shown.length"
		class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-gray-6"
		:aria-label="__('Document types')"
	>
		<li v-for="doctype in shown" :key="doctype" class="flex items-center gap-1.5">
			<DocumentTypeIcon :doctype="doctype" />
			{{ __(doctype) }}
		</li>
	</ul>
</template>
