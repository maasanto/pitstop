let messages = {};

export async function loadTranslations() {
	const response = await fetch(
		`/api/method/frappe.translate.get_boot_translations?lang=${window.lang || "en"}&v=${window.translations_version}`,
		{ headers: { Accept: "application/json" } },
	);
	if (!response.ok) {
		throw new Error(`Translations failed to load: HTTP ${response.status}`);
	}
	messages = (await response.json()).message || {};
}

// Both forms come in already translated: the string extractor only sees literal `__()` calls
export function _n(count, singular, plural) {
	return count === 1 ? singular : plural;
}

export function __(text, replacements = [], context = null) {
	const translated = (context && messages[`${text}:::${context}`]) || messages[text] || text;
	return translated.replace(/{(\d+)}/g, (match, index) => replacements[index] ?? match);
}
