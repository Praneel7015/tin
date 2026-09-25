# Pull request body and receipt

Use these headings, in this order, for both the pull request body and the receipt at
`reports/signup-source/{run_id}/RESULT.md`. A no-change result uses the same headings, with
`Outcome` naming the blocker and the operator step, and the change sections saying none.

## Outcome

`patch` or `no_change`, the repository, its revision, and in one sentence what a new account now
sees. For no-change, PLACEMENT.md's reason and the smallest step that would unblock a later run.

## Where it appears

The surface (`signup_form` or `first_screen`), the file and component, and why every new
account passes it exactly once.

## Answers offered

A table of every option in order: `value`, label, and evidence (`core`, or the path or URL that
shows this product uses the channel). Then the free-text box.

## Where answers are kept

The sink from PLACEMENT.md, the exact fields (`signup_source`, `signup_source_detail`), and the
file that writes them. Existing accounts are untouched.

## How to read them

The exact query, export or dashboard path that lists answers for this sink, ready to copy (for
example the SQL for a new column, or the metadata filter for the auth provider). Say when the
first read is worth doing: after about fifty new accounts, one answer is an anecdote.

## Verification

The checks actually run and their results, then the checks not run and why. Always include a
manual step: create one account on a preview deploy, answer the question, and find the answer
where "How to read them" says it is.

## Not changed

What was deliberately left alone: required fields, validation, auth and payment logic,
dependencies, tracking, and any second signup path found but not edited.
