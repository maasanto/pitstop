import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [
		frappeui({
			frontendRoute: "/pitstop",
			buildConfig: {
				outDir: "../pitstop/public/frontend",
				indexHtmlPath: "../pitstop/www/pitstop.html",
			},
		}),
		vue(),
	],
});
