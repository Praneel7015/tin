# Where the question goes and where the answer is kept

Collect the facts below from the repository, then call `choose_placement(facts)` from the single
Python block in this file, unchanged. It decides; you implement. If it returns `no_change`, change
no files and use its `reason` in the result.

Facts, each backed by a file path you can cite:

- `signup_in_repo`: this repository renders or handles account creation for the product.
- `already_asks`: it already asks new accounts where they came from (a field, column or property
  such as `hear_about`, `referral_source`, `signup_source`, `acquisition_channel`, `how_did_you`).
  UTM capture alone is not asking.
- `form`: `custom` when this repository renders the signup fields itself (its own inputs posting
  to its own handler or an auth SDK call), `hosted` when a provider renders them (a drop-in
  widget or a redirect to hosted login), `none` when there is no signup form at all.
- `first_screen`: this repository owns a screen every new account sees once right after signup
  (onboarding, welcome, workspace setup) and can save a value from it.
- `sinks`: every place this code can already write a per-account value, from `auth_metadata`
  (the auth SDK's user metadata written from existing signup or onboarding code),
  `profile_json` (an existing JSON or metadata column on the user or profile record),
  `migration` (a users table plus a migration tool the repository already uses, so a new
  nullable column is one migration file), `analytics_identify` (an existing analytics identify
  or person-property call made at signup).

Answers belong with the account. Analytics is the last resort: blockers drop it, it is sampled,
and a founder cannot join it to revenue later. A new table, endpoint, service or dependency is
never an option; that is infrastructure, not a question.

```python
FORMS = {"custom", "hosted", "none"}
SINK_ORDER = ("auth_metadata", "profile_json", "migration", "analytics_identify")
FILES_NEEDED = {"auth_metadata": 1, "profile_json": 1, "migration": 2, "analytics_identify": 1}


def choose_placement(facts, max_files=3):
    if not isinstance(facts, dict):
        raise ValueError("facts must be an object")
    for key in ("signup_in_repo", "already_asks", "first_screen"):
        if type(facts.get(key)) is not bool:
            raise ValueError(f"{key} must be true or false")
    form = facts.get("form")
    if form not in FORMS:
        raise ValueError("form must be custom, hosted or none")
    sinks = facts.get("sinks")
    if not isinstance(sinks, list) or any(sink not in SINK_ORDER for sink in sinks):
        raise ValueError(f"sinks must list only {', '.join(SINK_ORDER)}")
    if type(max_files) is not int or not 1 <= max_files <= 3:
        raise ValueError("max_files must be 1-3")

    def no_change(reason):
        return {"outcome": "no_change", "surface": None, "sink": None, "reason": reason}

    if not facts["signup_in_repo"]:
        return no_change(
            "signup is not in this repository; connect the repository that creates accounts"
        )
    if facts["already_asks"]:
        return no_change("new accounts are already asked where they came from; read those answers")
    if form == "custom":
        surface = "signup_form"
    elif facts["first_screen"]:
        surface = "first_screen"
    else:
        return no_change(
            "a hosted signup with no screen of yours after it; add a first-run screen, "
            "or turn on the provider's custom signup field"
        )
    for sink in SINK_ORDER:
        # The form or screen edit takes one file of the budget.
        if sink in sinks and FILES_NEEDED[sink] + 1 <= max_files:
            return {"outcome": "patch", "surface": surface, "sink": sink, "reason": ""}
    return no_change("no existing place keeps a value per account without new infrastructure")
```
