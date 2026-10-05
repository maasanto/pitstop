import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import "./style.css";
import { __, loadTranslations } from "./translation";

// frappe-ui's Button and Tabs expect a router; the page itself has a single route
const router = createRouter({
	history: createWebHistory("/bank-matching"),
	routes: [{ path: "/:pathMatch(.*)*", component: { render: () => null } }],
});

await loadTranslations();
const app = createApp(App);
app.config.globalProperties.__ = __;
app.use(router);
app.mount("#app");
