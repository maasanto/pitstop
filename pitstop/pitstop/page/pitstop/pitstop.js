// The desk route only exists so the awesomebar can find Pitstop: the page itself lives outside the desk
function openPitstop() {
	const params = new URLSearchParams(window.location.search);
	params.delete("sidebar");
	const query = params.toString();
	window.location.replace(query ? `/pitstop?${query}` : "/pitstop");
}

frappe.pages["pitstop"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Pitstop"), single_column: true });
	page.set_primary_action(__("Open Pitstop"), openPitstop);
};

// Not on_page_load, which fires once per desk session: a redirect cancelled by a "Leave site?" prompt
// would leave every later visit on this empty page
frappe.pages["pitstop"].on_page_show = openPitstop;
