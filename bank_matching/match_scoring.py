# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

"""How strongly a bank line points at a document.

No signal decides alone: an amount, a typed invoice number and a name in the label are each weak, and
only their combination makes a suggestion strong enough to preselect. Thresholds and weights were
backtested on the reconciliation history of several production sites.
"""

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

SHOW_THRESHOLD = 0.35
PRESELECT_THRESHOLD = 0.8
# Preselect only when no document of another party comes within this distance of the best one
PRESELECT_LEAD = 0.15

# How much each signal can contribute to the confidence, on its own
REFERENCE_WEIGHT = 0.75
AMOUNT_WEIGHT = 0.6
NAME_WEIGHT = 0.5
HISTORY_WEIGHT = 0.5

SAME_AMOUNT = 1.0
INVOICE_TOTAL = 0.8  # the invoice's full total, although part of it is already paid
ROUNDED_AMOUNT = 0.7  # within ROUNDING_TOLERANCE: 200 paid for 200.10
MISTYPED_AMOUNT = 0.4  # one digit wrong or two swapped: 1520 paid for 1250
AMOUNT_LESS_FEES = 0.3  # within FEES_TOLERANCE
ROUNDING_TOLERANCE = 0.005  # of the amount, and at least 1
FEES_TOLERANCE = 0.03

NAME_IN_LABEL = 1.0
CONTACT_IN_LABEL = 0.8
SURNAME_IN_LABEL = 0.4
SAME_WORD_RATIO = 90  # rapidfuzz ratio above which two words are the same word misspelt

EXACT = 1.0
YEAR_AND_COUNTER = 0.9
ONE_TYPO = 0.7
BARE_COUNTER = 0.5
TWO_TYPOS = 0.4
# Documents whose reference scores within this margin of the best one share its evidence
TIE_MARGIN = 0.15
# Below this, a reference only counts when the amount or a name backs it up
WEAK_REFERENCE = ONE_TYPO
# Shorter numbers are one typo away from too many others
MIN_LENGTH_FOR_ONE_TYPO = 8
MIN_LENGTH_FOR_TWO_TYPOS = 12
# rapidfuzz partial ratio under which a number cannot be one or two typos away: skips the costly search
TYPO_SEARCH_PREFILTER = 80

# `VIR-IL-0042` or `FAC 2026 0042`; a bank label pasted into a reference field runs longer
MAX_IDENTIFIER_WORDS = 3
# A word found in more than this share of the account's labels is boilerplate, unless it names few parties
COMMON_LABEL_WORD_SHARE = 0.02
MIN_COMMON_LABEL_WORD_COUNT = 3
MAX_PARTIES_SHARING_A_NAME_WORD = 2
LEGAL_FORMS_AND_TITLES = {
	"SAS",
	"SARL",
	"SASU",
	"EURL",
	"SCI",
	"THE",
	"LES",
	"DES",
	"MME",
	"MR",
	"MONSIEUR",
	"MADAME",
}
SIMILAR_LABEL = 0.5

# A card or platform settlement pays out the receipts of one to three days, within a week
MAX_BATCH_DAYS = 3
MAX_SETTLEMENT_DELAY = 7
MAX_SETTLEMENT_FEE = 0.035
# Consecutive receipts deposited together, all modes mixed, posted within this many days
MAX_RUN_DELAY = 45


def normalize(text: str | None) -> str:
	text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
	return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def words(text: str | None) -> set[str]:
	return {word for word in normalize(text).split() if len(word) >= 3 and not word.isdigit()}


def confidence(reference: float = 0, amount: float = 0, name: float = 0, history: float = 0) -> float:
	return 1 - (
		(1 - REFERENCE_WEIGHT * reference)
		* (1 - AMOUNT_WEIGHT * amount)
		* (1 - NAME_WEIGHT * name)
		* (1 - HISTORY_WEIGHT * history)
	)


def amount_grade(paid: float, outstanding: float, grand_total: float) -> float:
	paid, outstanding, grand_total = abs(paid), abs(outstanding), abs(grand_total)
	if not paid or not outstanding:
		return 0.0
	if abs(paid - outstanding) < 0.005:
		return SAME_AMOUNT
	if abs(paid - grand_total) < 0.005:
		return INVOICE_TOTAL
	if abs(paid - outstanding) <= max(1, ROUNDING_TOLERANCE * outstanding):
		return ROUNDED_AMOUNT
	paid_digits, outstanding_digits = f"{paid:.2f}", f"{outstanding:.2f}"
	# Same length only: a missing or extra digit is a tenfold difference, not a slip
	if (
		len(paid_digits) == len(outstanding_digits)
		and DamerauLevenshtein.distance(paid_digits, outstanding_digits) == 1
	):
		return MISTYPED_AMOUNT
	if abs(paid - outstanding) <= FEES_TOLERANCE * outstanding:
		return AMOUNT_LESS_FEES
	return 0.0


@dataclass(frozen=True)
class Reference:
	"""A document number, split so that `ACC-SINV-2026-00123` can be found as `2026-123`."""

	key: str
	compact: str
	year: str
	counter: str
	words: tuple

	@property
	def letters(self) -> str:
		return "".join(word for word in self.words if word.isalpha())

	@classmethod
	def parse(cls, key: str, number: str) -> "Reference":
		number_words = normalize(number).split()
		counter_words = number_words
		if _is_amendment_suffix(number_words):
			# `ACC-SINV-2026-00123-1` is amendment 1 of invoice 123: customers still write 123
			counter_words = number_words[:-1]
		counter = counter_words[-1].lstrip("0") if counter_words and counter_words[-1].isdigit() else ""
		year = next((word for word in counter_words[:-1] if _is_year(word)), "")
		return cls(key, "".join(number_words), year, counter, tuple(number_words))


def _is_year(word: str) -> bool:
	return bool(re.fullmatch(r"(19|20)\d\d", word))


def _is_amendment_suffix(number_words: list[str]) -> bool:
	return (
		len(number_words) >= 3
		and number_words[-1].isdigit()
		and len(number_words[-1]) <= 2
		and number_words[-2].isdigit()
		and not _is_year(number_words[-2])
	)


def reference_evidence(
	label: str, references: list[Reference], amount: float, dates: list
) -> dict[str, float]:
	"""Evidence per document key that the label designates it.

	The search runs over open AND closed documents: a typo landing between two consecutive invoice
	numbers, or on an invoice already paid, must not count as a match for an open neighbour.
	"""
	label = normalize(label)
	searched = SearchedLabel(label, _numbers_outside_noise(label, amount, dates))
	series_words = frozenset(word for ref in references for word in ref.words if word.isalpha())
	scores = {}
	for reference in references:
		score = _reference_score(reference, searched, series_words)
		if score > scores.get(reference.key, 0):
			scores[reference.key] = score
	if not scores:
		return {}
	top = max(scores.values())
	contenders = [key for key, score in scores.items() if score >= top - TIE_MARGIN]
	return {key: scores[key] / len(contenders) for key in contenders}


def is_identifier(number: str, compact_labels: list[str]) -> bool:
	"""A cheque, transfer or order number, not bank text copied into the field nor found in many labels.

	A payment created from a standing order often carries the order's fixed reference: it says who pays,
	not which document is paid, and would match every month's label.
	"""
	number_words = normalize(number).split()
	compact = "".join(number_words)
	if not 0 < len(number_words) <= MAX_IDENTIFIER_WORDS or sum(char.isdigit() for char in compact) < 3:
		return False
	labels_containing = sum(compact in label for label in compact_labels)
	return labels_containing <= max(3, COMMON_LABEL_WORD_SHARE * len(compact_labels))


def _numbers_outside_noise(label: str, amount: float, dates: list) -> list[str]:
	"""Standalone numbers of the label, minus the transaction's own amount and dates."""
	noise = {f"{abs(amount):.2f}".replace(".", ""), str(int(abs(amount)))}
	for date in dates:
		noise |= {date.strftime(fmt) for fmt in ("%d%m%y", "%d%m%Y", "%Y%m%d", "%y%m%d")}
	return [run for run in re.findall(r"\d+", label) if run not in noise]


class SearchedLabel:
	"""A normalized label in the forms the reference search needs, computed once for all documents."""

	def __init__(self, label: str, runs: list[str]):
		self.text = label
		self.compact = label.replace(" ", "")
		self.runs = runs
		self.word_edges = {0}
		position = 0
		for word in label.split():
			position += len(word)
			self.word_edges.add(position)


def _reference_score(reference: Reference, label: SearchedLabel, series_words: frozenset) -> float:
	if len(reference.compact) >= 4 and _contains_whole_number(label, reference.compact):
		return EXACT
	# The counter's digits appear verbatim in any year-and-counter form: skip the regexes otherwise
	if (
		reference.year
		and reference.counter
		and reference.counter in label.compact
		and _year_and_counter_found(reference, label.text, series_words)
	):
		return YEAR_AND_COUNTER
	if (
		len(reference.compact) >= MIN_LENGTH_FOR_ONE_TYPO
		and fuzz.partial_ratio(reference.compact, label.compact) >= TYPO_SEARCH_PREFILTER
	):
		distance = _min_window_distance(reference.compact, label.compact)
		if distance == 1:
			return ONE_TYPO
		if distance == 2 and len(reference.compact) >= MIN_LENGTH_FOR_TWO_TYPOS:
			return TWO_TYPOS
	if len(reference.counter) >= 3 and any(run.lstrip("0") == reference.counter for run in label.runs):
		return BARE_COUNTER
	return 0.0


def _contains_whole_number(label: SearchedLabel, needle: str) -> bool:
	"""`FA20261` must not match inside `FA202612`, but may end where the label had a space."""
	if needle not in label.compact:
		return False
	for found in re.finditer(re.escape(needle), label.compact):
		start, end = found.span()
		starts_clean = start in label.word_edges or not label.compact[start - 1].isdigit()
		ends_clean = end in label.word_edges or not label.compact[end].isdigit()
		if starts_clean and ends_clean:
			return True
	return False


def _year_and_counter_found(reference: Reference, label: str, series_words: frozenset) -> bool:
	"""`2026-123` or `SINV 26 00123`, never a date like `25/01` for counter 1 of 2025.

	Without the series letters the year must be written in full and the counter have 3+ digits,
	otherwise `ACC-PAY-2025-00001` would match every label dated 25/01 and every `FAC-2025-00001`.
	"""
	counter = rf"\D?0*{reference.counter}(?!\d)"
	years = f"(?:{reference.year}|{reference.year[2:]})"
	if reference.letters and re.search(rf"{reference.letters}{years}{counter}", label.replace(" ", "")):
		return True
	if len(reference.counter) < 3:
		return False
	other_series = series_words - set(reference.words)
	for found in re.finditer(rf"(?<![\dA-Z]){reference.year}{counter}", label):
		preceding = label[: found.start()].split()[-1:]
		if not (preceding and preceding[0] in other_series):
			return True
	return False


def _min_window_distance(needle: str, haystack: str) -> int:
	# ponytail: brute-force sliding window, O(label length) per document; a deletion index if the
	# indexed documents grow past ~10k.
	best = len(needle)
	for size in (len(needle) - 1, len(needle), len(needle) + 1):
		for start in range(0, max(1, len(haystack) - size + 1)):
			best = min(best, DamerauLevenshtein.distance(needle, haystack[start : start + size]))
			if best == 0:
				return 0
	return best


class Vocabulary:
	"""Which words of a label can identify a party.

	A word repeated across the account's labels is boilerplate (the company's own name, the bank's
	wording, a city) unless it belongs to at most two parties: then it is the name of a regular payer.
	"""

	def __init__(self, labels: list[str], party_names: list[str]):
		self.label_frequency = Counter(word for label in labels for word in words(label))
		# On a young account, a word seen in a couple of labels is still nobody's boilerplate
		self.common_threshold = max(MIN_COMMON_LABEL_WORD_COUNT, COMMON_LABEL_WORD_SHARE * len(labels))
		self.name_owners = Counter(word for name in party_names for word in words(name))

	def is_identifying(self, word: str) -> bool:
		if word in LEGAL_FORMS_AND_TITLES:
			return False
		return (
			self.label_frequency[word] <= self.common_threshold
			or 0 < self.name_owners[word] <= MAX_PARTIES_SHARING_A_NAME_WORD
		)

	def label_words(self, label: str) -> set[str]:
		return {word for word in words(label) if self.is_identifying(word)}


def name_grade(
	label: str,
	label_words: set[str],
	bank_party_name: str | None,
	party: str | None,
	party_name: str | None,
	contacts: list[tuple[str, str]],
	vocabulary: Vocabulary,
) -> float:
	"""How surely the label names the party: its name or code, a contact's full name, or a surname."""
	name_words = {word for word in words(party_name) if vocabulary.is_identifying(word)}
	found = {word for word in name_words if _word_found(word, label_words)}
	if name_words and len(found) >= min(2, len(name_words)):
		return NAME_IN_LABEL
	if (
		bank_party_name
		and party_name
		and fuzz.token_sort_ratio(normalize(bank_party_name), normalize(party_name)) >= SAME_WORD_RATIO
	):
		return NAME_IN_LABEL
	if _code_in_label(party, label):
		return NAME_IN_LABEL
	best = 0.0
	for first_name, last_name in contacts:
		last, first = normalize(last_name), normalize(first_name)
		if len(last) >= 3 and vocabulary.is_identifying(last) and _word_found(last, label_words):
			if first and _word_found(first, label_words):
				return CONTACT_IN_LABEL
			best = SURNAME_IN_LABEL
	return best


def _code_in_label(party: str | None, label: str) -> bool:
	"""The party's code, `CUST-00042` written `CUST00042` or `cust 00042`, as whole words of the label.

	Only codes with digits: a party named by its name goes through the name rules and their rarity check.
	"""
	code_words = normalize(party).split()
	code = "".join(code_words)
	if len(code) < 5 or not any(char.isdigit() for char in code):
		return False
	pattern = r" ?".join(re.escape(word) for word in code_words)
	return bool(re.search(rf"(?<![A-Z0-9]){pattern}(?![A-Z0-9])", normalize(label)))


def _word_found(word: str, label_words: set[str]) -> bool:
	return word in label_words or (
		len(word) >= 5 and any(fuzz.ratio(word, other) >= SAME_WORD_RATIO for other in label_words)
	)


def past_payers(label_words: set[str], history: list[tuple[set[str], set[str]]]) -> dict[str, float]:
	"""Parties that earlier lines with a similar label were reconciled with, weighted by similarity.

	One similar line gives half the weight; two or more give it all.
	"""
	votes = Counter()
	for past_words, parties in history:
		union = label_words | past_words
		similarity = len(label_words & past_words) / len(union) if union else 0
		if similarity >= SIMILAR_LABEL:
			for party in parties:
				votes[party] += similarity
	total = sum(votes.values())
	if not total:
		return {}
	support = min(1.0, total / 2)
	return {party: support * count / total for party, count in votes.items()}


@dataclass(frozen=True)
class Receipt:
	"""A payment already posted and not yet reconciled, that a settlement may pay out."""

	key: str
	amount: float
	posting_date: date
	mode_of_payment: str | None


@dataclass(frozen=True)
class Settlement:
	keys: tuple
	total: float
	fee: float


def settlement_batches(amount: float, paid_on: date, receipts: list[Receipt]) -> list[Settlement]:
	"""Groups of receipts one bank line pays out at once, the likeliest first.

	A card or platform batch is every receipt of one mode of payment over one to three days, paid whole
	or less a fee. Failing an exact batch, a run of consecutive receipts adding up to the amount: a deposit
	of cheques or cash collected over several days.
	"""
	amount_cents = _cents(amount)
	posted = [receipt for receipt in receipts if receipt.posting_date <= paid_on]
	exact, less_fees = _day_batches(amount_cents, paid_on, posted)
	if exact:
		return exact
	recent = [receipt for receipt in posted if (paid_on - receipt.posting_date).days <= MAX_RUN_DELAY]
	return _consecutive_run(amount_cents, recent) + less_fees


def _cents(amount: float) -> int:
	return round(abs(amount) * 100)


def _day_batches(amount_cents: int, paid_on: date, receipts: list[Receipt]):
	by_mode = defaultdict(list)
	for receipt in receipts:
		if (paid_on - receipt.posting_date).days <= MAX_SETTLEMENT_DELAY:
			by_mode[receipt.mode_of_payment or ""].append(receipt)
	exact, less_fees = [], []
	for pool in by_mode.values():
		dates = sorted({receipt.posting_date for receipt in pool})
		for start in dates:
			for end in dates:
				if not 0 <= (end - start).days < MAX_BATCH_DAYS:
					continue
				batch = [receipt for receipt in pool if start <= receipt.posting_date <= end]
				if len(batch) < 2:
					continue
				total = sum(_cents(receipt.amount) for receipt in batch)
				settlement = Settlement(
					tuple(receipt.key for receipt in batch), total / 100, (total - amount_cents) / 100
				)
				if total == amount_cents:
					exact.append(((-end.toordinal(), (end - start).days), settlement))
				elif 0 < total - amount_cents <= MAX_SETTLEMENT_FEE * total:
					less_fees.append((total - amount_cents, settlement))
	return (
		[settlement for _, settlement in sorted(exact, key=lambda ranked: ranked[0])],
		[settlement for _, settlement in sorted(less_fees, key=lambda ranked: ranked[0])],
	)


def _consecutive_run(amount_cents: int, receipts: list[Receipt]) -> list[Settlement]:
	ordered = sorted(receipts, key=lambda receipt: (receipt.posting_date, receipt.key))
	for end in range(len(ordered) - 1, 0, -1):
		total = _cents(ordered[end].amount)
		for start in range(end - 1, -1, -1):
			total += _cents(ordered[start].amount)
			if total == amount_cents:
				return [
					Settlement(tuple(receipt.key for receipt in ordered[start : end + 1]), total / 100, 0)
				]
			if total > amount_cents:
				break
	return []
