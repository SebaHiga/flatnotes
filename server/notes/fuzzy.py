"""fzf-style fuzzy subsequence matching.

Unlike Whoosh's built-in fuzzy term support (which is edit-distance based,
e.g. tolerating "meetign" -> "meeting"), this implements the other common
style of "fuzzy" search popularised by fzf/Sublime Text's "Goto Anything":
a query only needs to appear as an ordered (not necessarily contiguous)
subsequence of the target, ranked by how tight/contiguous the match is and
whether it lands on word boundaries.
"""

import html
from typing import List, Optional, Tuple

SEPARATORS = set(" -_./\\")

SEQUENTIAL_BONUS = 15  # Bonus for matching the very next character.
SEPARATOR_BONUS = 30  # Bonus for matching right after a separator.
CAMEL_BONUS = 30  # Bonus for matching a camelCase hump.
FIRST_LETTER_BONUS = 15  # Bonus for matching the first character.
LEADING_LETTER_PENALTY = 5  # Penalty per character before the first match.
MAX_LEADING_LETTER_PENALTY = 15  # Cap on the leading-letter penalty.
UNMATCHED_LETTER_PENALTY = 1  # Penalty per unmatched character (gap).
# Bonus per character when the whole pattern appears as a literal, unbroken
# substring, so a clean match always outranks a scattered/acronym-style one
# of similar length (e.g. "note" in "Note" should beat "note" scattered
# across "Not Every Testcase Ever").
EXACT_SUBSTRING_BONUS_PER_CHAR = 20

NEG_INF = float("-inf")


def _char_match_bonus(text_lower: str, j: int) -> int:
    """Bonus for matching character at index `j` of `text_lower`, based on
    what precedes it."""
    if j == 0:
        return FIRST_LETTER_BONUS
    prev_char = text_lower[j - 1]
    if prev_char in SEPARATORS:
        return SEPARATOR_BONUS
    if prev_char.islower() and text_lower[j].isupper():
        return CAMEL_BONUS
    return 0


def _is_subsequence(pattern_lower: str, text_lower: str) -> bool:
    it = iter(text_lower)
    return all(char in it for char in pattern_lower)


def _match_single(
    pattern: str, text: str
) -> Optional[Tuple[float, List[int]]]:
    """Case-insensitive fzf-style subsequence match of `pattern` against
    `text`. Returns (score, matched_indices) or None if `pattern` is not a
    subsequence of `text`."""
    if not pattern:
        return (0.0, [])
    pattern_lower = pattern.lower()
    text_lower = text.lower()
    n, m = len(pattern_lower), len(text_lower)
    if n > m or not _is_subsequence(pattern_lower, text_lower):
        return None

    # dp[i][j]: best score for matching pattern[:i + 1] with its i-th
    # character landing at text index j. back[i][j]: the text index the
    # (i - 1)-th character landed at for that best score.
    dp = [[NEG_INF] * m for _ in range(n)]
    back = [[-1] * m for _ in range(n)]

    for j in range(m):
        if pattern_lower[0] == text_lower[j]:
            penalty = min(
                j * LEADING_LETTER_PENALTY, MAX_LEADING_LETTER_PENALTY
            )
            dp[0][j] = 1 + _char_match_bonus(text_lower, j) - penalty

    for i in range(1, n):
        # Running best of dp[i - 1][j''] + UNMATCHED_LETTER_PENALTY * (j'' + 1)
        # for j'' <= j - 2, i.e. every earlier match at least one character
        # before the previous slot. Kept incrementally so the whole row is
        # O(m) instead of O(m^2).
        running_best = NEG_INF
        running_best_j = -1
        for j in range(m):
            candidate_j = j - 2
            if candidate_j >= 0 and dp[i - 1][candidate_j] > NEG_INF:
                val = dp[i - 1][candidate_j] + UNMATCHED_LETTER_PENALTY * (
                    candidate_j + 1
                )
                if val > running_best:
                    running_best = val
                    running_best_j = candidate_j

            if pattern_lower[i] != text_lower[j]:
                continue

            best_val = NEG_INF
            best_prev_j = -1
            # Adjacent: the previous pattern character matched directly
            # before this one.
            if j - 1 >= 0 and dp[i - 1][j - 1] > NEG_INF:
                val = dp[i - 1][j - 1] + SEQUENTIAL_BONUS
                if val > best_val:
                    best_val = val
                    best_prev_j = j - 1
            # Non-adjacent: best earlier match, penalized for the gap.
            if running_best > NEG_INF:
                val = running_best - UNMATCHED_LETTER_PENALTY * j
                if val > best_val:
                    best_val = val
                    best_prev_j = running_best_j

            if best_val > NEG_INF:
                dp[i][j] = best_val + _char_match_bonus(text_lower, j)
                back[i][j] = best_prev_j

    best_j = max(range(m), key=lambda j: dp[n - 1][j])
    if dp[n - 1][best_j] == NEG_INF:
        return None  # pragma: no cover - guarded by the subsequence check above

    indices = [0] * n
    j = best_j
    for i in range(n - 1, -1, -1):
        indices[i] = j
        j = back[i][j]

    score = dp[n - 1][best_j]
    if pattern_lower in text_lower:
        score += EXACT_SUBSTRING_BONUS_PER_CHAR * n
    return (score, indices)


def fuzzy_score(
    query: str, text: str
) -> Optional[Tuple[float, List[int]]]:
    """Match `query` against `text`, fzf-style.

    `query` is split on whitespace into tokens; every token must
    independently match as a subsequence of `text` (AND semantics, as in
    fzf). Returns (combined_score, matched_indices) or None if any token
    fails to match.
    """
    tokens = query.split()
    if not tokens:
        return None
    total_score = 0.0
    matched_indices = set()
    for token in tokens:
        result = _match_single(token, text)
        if result is None:
            return None
        score, indices = result
        total_score += score
        matched_indices.update(indices)
    return (total_score, sorted(matched_indices))


def highlight(text: str, indices: List[int]) -> str:
    """HTML-escape `text` and wrap contiguous runs of `indices` in
    `<b class="match">`, matching the convention Whoosh's highlighter
    already uses for non-fuzzy search results."""
    if not indices:
        return html.escape(text)
    parts = []
    pos = 0
    sorted_indices = sorted(set(indices))
    i = 0
    n = len(sorted_indices)
    while i < n:
        start = sorted_indices[i]
        end = start
        while i + 1 < n and sorted_indices[i + 1] == end + 1:
            i += 1
            end = sorted_indices[i]
        parts.append(html.escape(text[pos:start]))
        parts.append('<b class="match">')
        parts.append(html.escape(text[start : end + 1]))
        parts.append("</b>")
        pos = end + 1
        i += 1
    parts.append(html.escape(text[pos:]))
    return "".join(parts)


CONTENT_SNIPPET_CONTEXT_CHARS = 60


def content_snippet(text: str, indices: List[int]) -> str:
    """Return an HTML-highlighted snippet of `text` centered on `indices`,
    truncated with ellipses, similar in spirit to Whoosh's
    ContextFragmenter."""
    if not indices:
        return ""
    start = max(0, min(indices) - CONTENT_SNIPPET_CONTEXT_CHARS)
    end = min(len(text), max(indices) + 1 + CONTENT_SNIPPET_CONTEXT_CHARS)
    window = text[start:end]
    shifted_indices = [idx - start for idx in indices if start <= idx < end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + highlight(window, shifted_indices) + suffix
