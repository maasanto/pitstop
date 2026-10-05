<script setup>
import { Button, Dialog } from "frappe-ui";
import { computed } from "vue";
import { deskUrl } from "../format";

const props = defineProps({ document: { type: Object, default: null } });
const open = defineModel("open", { type: Boolean, default: false });

const printUrl = computed(
	() =>
		props.document &&
		`/printview?doctype=${encodeURIComponent(props.document.doctype)}&name=${encodeURIComponent(props.document.name)}&trigger_print=0`,
);
</script>

<template>
	<Dialog v-model:open="open" size="5xl" :title="document?.name">
		<iframe
			v-if="printUrl"
			:src="printUrl"
			class="h-[70vh] w-full rounded-4 border border-outline-gray-1 bg-white"
		/>
		<template #actions>
			<div class="flex justify-end">
				<Button
					v-if="document"
					icon-left="lucide-external-link"
					:label="__('Open in Dokos')"
					:link="deskUrl(document.doctype, document.name)"
				/>
			</div>
		</template>
	</Dialog>
</template>
