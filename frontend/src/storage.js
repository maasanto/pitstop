// Storage can be blocked (private window, cleared site data): the page then simply forgets between visits
export function readStored(key) {
	try {
		return JSON.parse(localStorage.getItem(key));
	} catch {
		return null;
	}
}

export function writeStored(key, value) {
	try {
		localStorage.setItem(key, JSON.stringify(value));
	} catch {
		// Nothing to recover: the value lives until the page is left
	}
}
