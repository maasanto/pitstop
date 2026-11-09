// The desk route only exists so the awesomebar can find Pitstop: the page itself lives outside the desk
frappe.pages["pitstop"].on_page_load = () => window.location.replace("/pitstop");
