app_name = "bank_matching"
app_title = "Bank Matching"
app_publisher = "Antoine Maas"
app_description = "Bank reconciliation that starts from the pairings Dokos already found"
app_email = "antoine.maas@gmail.com"
app_license = "agpl-3.0"

required_apps = ["erpnext"]

use_json_request_body = True
require_type_annotated_api_methods = True

website_route_rules = [{"from_route": "/bank-matching/<path:app_path>", "to_route": "bank-matching"}]

# A refusal belongs to its line: it must neither block the line's deletion nor outlive it
ignore_links_on_delete = ["Bank Match Refusal"]
doc_events = {"Bank Transaction": {"on_trash": "bank_matching.refusals.delete_line_refusals"}}

doctype_js = {
	"Sales Invoice": "public/js/find_bank_line.js",
	"Purchase Invoice": "public/js/find_bank_line.js",
	"Payment Entry": "public/js/find_bank_line.js",
}
