---
title: Ranking error-message content opportunities
---

# Why a formula and not judgment

A user who hits an error copies text into a search box. What they paste is the part of the
message that does not change between runs, so the invariant text is the whole asset. A message
that is mostly interpolated values has no searchable core no matter how often it fires, and a
message built from generic words competes with the entire internet. Both facts are computable,
which is why this file decides and the model only supplies evidence.

Score every candidate with `rank_candidates`. Do not re-order the result, do not promote a
candidate the formula rejected, and do not invent a score.

## The inputs you must observe

Each candidate is a dict:

- `message`: the string exactly as the code spells it, placeholders intact.
- `surface`: `user_facing`, `api`, `cli`, `operator` or `internal`, decided by reading the
  emitting path.
- `call_sites`: how many distinct `path:line` locations raise it, as an integer.
- `coverage`: `none`, `partial` or `documented`, decided by reading the repository's own docs.
- `evidence`: a `path:line` string you read yourself.

Pass `operator_weight=SELF_HOSTED_OPERATOR_WEIGHT` when the run's `self_hosted` input is true.
An `operator` message — one that names an environment variable, a credential or a deploy setting —
is read by whoever installs the product. For a hosted product that is the founder's own team, so
it is worth almost nothing as content. For a product people run themselves it is worth as much as
any other user-facing message, and the same string has to score differently in the two worlds.

## The scoring

```python
"""Deterministic scoring for error-message content opportunities."""

import math
import re

SURFACE_WEIGHTS = {
    "user_facing": 1.0,
    "api": 0.9,
    "cli": 0.8,
    "operator": 0.15,
    "internal": 0.0,
}
COVERAGE_FACTORS = {"none": 1.0, "partial": 0.4, "documented": 0.0}
# An operator message reaches whoever deploys the product, not whoever uses it. For a hosted
# product that is nobody outside the team; for a self-hosted one they are the whole audience.
# Pass operator_weight to say which product this is.
SELF_HOSTED_OPERATOR_WEIGHT = 0.9

# Words that carry no distinguishing search intent on their own.
GENERIC_TOKENS = frozenset(
    """a an the is was be to of in on at for with and or not error errors failed failure
    invalid unknown unexpected bad wrong cannot can could unable something went please try
    again occurred request response server internal input value data missing required found
    exists empty null none true false this that it you your we our there has have had""".split()
)

_PLACEHOLDER = re.compile(
    r"\{[^{}]*\}"  # {}, {0}, {name}
    r"|%\([^)]*\)[a-zA-Z]"  # %(name)s
    r"|%[-+0-9.#]*[a-zA-Z]"  # %s, %d, %-10s
    r"|\$\{[^{}]*\}"  # ${name}
    r"|\$[A-Za-z_][A-Za-z0-9_]*"  # $name
    r"|<[A-Za-z_][A-Za-z0-9_ .-]*>"  # <path>
)
_CODE_CANDIDATE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)+|\b[A-Z]{1,8}-?\d{3,6}\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _text(message):
    if not isinstance(message, str):
        raise ValueError("message must be a string")
    return message.strip()


def code_tokens(message):
    """Error codes a user would paste verbatim, such as ERR_CONN_REFUSED or PGRST116."""
    tokens = []
    for token in _CODE_CANDIDATE.findall(_text(message)):
        if len(token) < 4 or not token[:1].isupper():
            continue
        separators = token.count("_") + token.count("-")
        # A code either carries digits or is a multi-part SCREAMING_SNAKE identifier.
        if any(character.isdigit() for character in token) or separators >= 2:
            if token.upper() == token:
                tokens.append(token)
    return tokens


def invariant_runs(message):
    """The literal fragments left once every interpolated value is removed."""
    return [run.strip() for run in _PLACEHOLDER.split(_text(message)) if run.strip()]


def _placeholder_fraction(message):
    text = _text(message)
    if not text:
        return 0.0
    consumed = sum(len(match.group(0)) for match in _PLACEHOLDER.finditer(text))
    return min(1.0, consumed / len(text))


def _length_credit(count):
    """Credit for invariant length, still rising at twenty words rather than capping at five.

    A linear cap treated a three-word fragment and a sentence that names the fix as equally
    specific. This keeps separating them, with diminishing returns, and saturates near twenty.
    """
    if count <= 0:
        return 0
    return round(35 * min(1.0, math.log(1 + count, 2) / math.log(21, 2)))


def searchability(message):
    """0-100: how findable this message is when a user pastes it into a search box."""
    text = _text(message)
    if not text:
        return 0
    runs = invariant_runs(text)
    words = max((_WORD.findall(run) for run in runs), key=len, default=[])
    codes = code_tokens(text)
    distinctive = [word for word in words if word.lower() not in GENERIC_TOKENS]
    # Without a code, a fragment needs three words and at least one that is not a stock
    # error word. Length alone is not identity: "Something went wrong" clears the word
    # count and is still the most-written sentence on the internet.
    if not codes and (len(words) < 3 or not distinctive):
        return 0
    score = 40 if codes else 0
    score += _length_credit(len(words))
    if words:
        score += round(25 * len(distinctive) / len(words))
    score -= round(20 * _placeholder_fraction(text))
    return max(0, min(100, score))


def reach_weight(call_sites):
    """More emitting paths means more users arrive at the same message."""
    if type(call_sites) is not int or call_sites < 0:
        raise ValueError("call_sites must be a non-negative integer")
    if call_sites == 0:
        return 0.0
    return round(min(1.0, 0.6 + 0.4 * math.log(call_sites + 1, 5)), 3)


def _operator_weight(value):
    if value is None:
        return SURFACE_WEIGHTS["operator"]
    if type(value) not in (int, float) or isinstance(value, bool) or not 0.0 <= value <= 1.0:
        raise ValueError("operator_weight must be a number between 0 and 1")
    return float(value)


def score_candidate(candidate, operator_weight=None):
    """Return the candidate with its score and the decision the formula reached."""
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a dict")
    missing = {"message", "surface", "call_sites", "coverage"} - set(candidate)
    if missing:
        raise ValueError(f"candidate is missing {sorted(missing)}")
    surface, coverage = candidate["surface"], candidate["coverage"]
    if surface not in SURFACE_WEIGHTS:
        raise ValueError(f"unsupported surface {surface!r}")
    if coverage not in COVERAGE_FACTORS:
        raise ValueError(f"unsupported coverage {coverage!r}")
    weight = (
        _operator_weight(operator_weight) if surface == "operator" else SURFACE_WEIGHTS[surface]
    )
    found = searchability(candidate["message"])
    reach = reach_weight(candidate["call_sites"])
    score = found * weight * reach * COVERAGE_FACTORS[coverage]
    if weight == 0.0:
        # Nobody outside the team reads it, whatever it says.
        decision = "internal_only"
    elif found == 0:
        decision = "not_searchable"
    elif coverage == "documented":
        decision = "already_covered"
    elif reach == 0.0:
        decision = "unreachable"
    else:
        decision = "write_page"
    return {
        **candidate,
        "searchability": found,
        "reach_weight": reach,
        "score": round(score, 1),
        "decision": decision,
    }


def rank_candidates(candidates, max_opportunities=15, operator_weight=None):
    """Bucket every candidate by decision and rank the page-worthy ones."""
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    if type(max_opportunities) is not int or not 1 <= max_opportunities <= 40:
        raise ValueError("max_opportunities must be an integer between 1 and 40")
    _operator_weight(operator_weight)
    buckets = {
        "opportunities": [],
        "deferred": [],
        "already_covered": [],
        "not_searchable": [],
        "internal_only": [],
        "unreachable": [],
    }
    scored = [score_candidate(candidate, operator_weight) for candidate in candidates]
    messages = [item["message"] for item in scored]
    if len(set(messages)) != len(messages):
        raise ValueError("candidates contain duplicate messages")
    page_worthy = sorted(
        (item for item in scored if item["decision"] == "write_page"),
        key=lambda item: (-item["score"], item["message"]),
    )
    buckets["opportunities"] = page_worthy[:max_opportunities]
    buckets["deferred"] = page_worthy[max_opportunities:]
    for item in scored:
        if item["decision"] != "write_page":
            buckets[item["decision"]].append(item)
    for name in ("already_covered", "not_searchable", "internal_only", "unreachable"):
        buckets[name].sort(key=lambda item: item["message"])
    return buckets
```

## Reading the result

`opportunities` is the ranked table. `deferred` are page-worthy but below the requested cut, and
they belong in the report as a named count, not as silence. The other buckets are the finding
that matters most to a founder who believes every error deserves a page: `not_searchable` means
the message cannot be found no matter how well the page is written, and the repair is a better
error string in the product, not an article.
