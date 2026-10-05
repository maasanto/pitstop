import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [
		frappeui({
			frontendRoute: "/bank-matching",
			buildConfig: {
				outDir: "../bank_matching/public/frontend",
				indexHtmlPath: "../bank_matching/www/bank-matching.html",
			},
		}),
		vue(),
	],
});
