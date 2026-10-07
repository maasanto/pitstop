<script setup>
import { Tooltip } from "frappe-ui";
import { computed } from "vue";
import { DOCUMENT_TYPES } from "../format";
import { __ } from "../translation";

const props = defineProps({
	doctype: { type: String, required: true },
	size: { type: String, default: "md", validator: (size) => ["md", "lg"].includes(size) },
});

const documentType = computed(
	() => DOCUMENT_TYPES[props.doctype] ?? { icon: "lucide-file", tint: "bg-surface-gray-2 text-ink-gray-6" },
);
</script>

<template>
	<Tooltip :text="__(doctype)">
		<span
			class="flex shrink-0 items-center justify-center"
			:class="[documentType.tint, size === 'lg' ? 'size-9 rounded-6' : 'size-6 rounded-4']"
			role="img"
			:aria-label="__(doctype)"
		>
			<span :class="[documentType.icon, size === 'lg' ? 'size-5' : 'size-3.5']" aria-hidden="true" />
		</span>
	</Tooltip>
</template>
