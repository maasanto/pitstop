// The desk route only exists so the awesomebar can find Pitstop: the page itself lives outside the desk
frappe.pages["pitstop"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Pitstop"), single_column: true });
	page.set_primary_action(__("Open Pitstop"), wrapper.on_page_show);
};

// Not on_page_load, which fires once per desk session: a redirect cancelled by a "Leave site?" prompt
// would leave every later visit on this empty page
frappe.pages["pitstop"].on_page_show = () => window.location.replace(`/pitstop${window.location.search}`);
