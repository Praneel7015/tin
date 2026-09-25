# Free tool qualification

The cases in `qualification.json` use the normal package qualification contract. They
are test specifications, not evidence that an agent passed them. Each case names the
repository shape its authorized evaluation must connect; `https://example.com/` stands in
for that evaluation's own product page.

- `ordinary` needs reusable, public-safe domain logic and an open results page.
- `thin_repository` needs only CRUD, auth and billing glue. "No tool worth building" at
  `Status: complete` is the correct answer; a forced pick fails.
- `sensitive_logic_vetoed` is the plausible but unusable case: cheap, searched-for, and
  built on proprietary scoring. It must be rejected as `sensitive-logic`.
- `crowded_phrase_rejected` checks that strong demand does not beat a first page held by
  established tool sites.
- `exclude_is_honoured` checks that the founder's exclusion is a hard rule.

Run `uv run pytest tests/test_free_tool.py` and
`uv run python -m tin_lite.workflow_qualification_cli check workflow_packages/growth.free_tool/workflow.json`
offline. Neither executes the procedure. A live evaluation needs an authorized Tin project
with a connected fixture repository, a named payer and a spending ceiling. Review the
retained report by hand against the rubric: open every cited URL and `path:line`. A report
with the right headings and a fabricated citation is a failure.
