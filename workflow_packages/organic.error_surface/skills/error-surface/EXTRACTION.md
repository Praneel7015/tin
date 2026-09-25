---
title: Finding the messages a user can actually see
---

# What counts as a candidate

A candidate is a string the product shows to somebody outside the team: an API error body, a CLI
stderr line, a toast or form error in the interface, an exception message that reaches a user's
terminal. A log line at debug level, an internal assertion, and a test fixture are not
candidates. When you cannot tell from the raise site, read the handler that catches it: a message
that is swallowed and replaced never reaches a user, and the replacement is the candidate.

Record the string as the source spells it, with placeholders intact. Never normalize, translate,
or tidy a message; the invariant text is the whole asset and editing it destroys the evidence.

## Where to look first

Orient before grepping. When `/home/user/state/wiki/INDEX.md` has a `### Code map`, start from
its user-facing surfaces and their cited files. Then read the README, the package manifest, and
the route or command table so you know which directories are user-facing. Then work outward from the product's own error
vocabulary, because a codebase that defines error classes or an error-code enum has already done
the extraction for you:

1. A central error module: `errors.*`, `exceptions.*`, `error_codes.*`, `problems.*`.
2. An enum, constant map, or catalogue of codes and their default messages.
3. The API serializer that renders an error body, which shows the exact user-visible shape.
4. The interface's error strings, including any i18n catalogue.

An i18n catalogue is the best source in the repository when it exists: it is the complete list of
user-visible strings, already separated from internal ones. Prefer the default-locale file.

## Patterns

These find raise sites and message constants across common stacks. Run them from
`/home/user/project` and widen only when a stack is not covered.

```bash
# Constructed error objects carrying literal text. Match the constructor, never the keyword in
# front of it. `reject(new Error(...))`, `return new Error(...)` and `const err = new Error(...)`
# are at least as common as `throw` in promise and callback code, and a throw-anchored pattern
# loses them silently: nothing appears in the inventory to tell you they were missed.
rg -n --no-heading -g '!test*' -g '!*_test.*' -g '!*.spec.*' \
  "new \w*Error\(|raise \w+(Error|Exception)\(|errors\.New\(|fmt\.Errorf\(|panic\("

# Error-code catalogues and message constants
rg -n --no-heading "ERROR_CODES|error_codes|ErrorCode|ERR_[A-Z0-9_]+|\bE[0-9]{3,5}\b"

# Rendered API error bodies
rg -n --no-heading "detail=|\"message\":|message:|user_message|client_message"

# Interface strings and translation catalogues
rg -n --no-heading -g '*.json' -g '*.yaml' -g '*.yml' "\"errors?\"\s*:" locales/ i18n/ 2>/dev/null
```

Exclude tests, fixtures, mocks, vendored dependencies, and generated files. A message that only
exists in a test is evidence about the test, not about the product.

## Deciding the surface

Read the emitting path and choose one value. Do not guess from the message text.

- `user_facing`: reaches a browser, an email, or a rendered screen.
- `api`: returned in a response body to an integrator.
- `cli`: written to stdout or stderr of a command a user runs.
- `operator`: reaches whoever installs or deploys the product, not whoever uses it. A message that
  names an environment variable, a credential, a bucket or a region is almost always this —
  `UPSTASH_REDIS_URL is not set` is read by the person configuring the service, not by a customer.
  Classify it `operator` unless you read a path showing an ordinary user reaching it.
- `internal`: assertions, debug logs, developer tooling, or anything a handler replaces before it
  reaches a user. Internal candidates score zero by construction; record them and move on.

`operator` is the classification most often got wrong, in both directions. An environment-variable
name is a genuinely searchable string, so the formula will happily rank it high, and for a product
people self-host that is correct. For a hosted product nobody outside the team ever sees it.
Decide by reading who runs the code that throws, and let the run's `self_hosted` input carry the
product model into the score; do not settle it by lowering the message's searchability.

## Counting call sites

`call_sites` is the number of distinct `path:line` locations that raise or return the same
message. Count a constant's references, not its single definition: a code that is defined once and
raised from eleven places has eleven call sites. Count each location once even when a loop or a
retry can emit it repeatedly, because this measures how many code paths lead a user here, not how
often it fires. You have no runtime telemetry in this run and must not imply that you do.

## Deciding coverage

Search the repository's own documentation before calling a message uncovered. Use the run's
`docs_paths` when given; otherwise discover them, typically `docs/`, `content/`, `website/`,
`help/`, or a `docs` site directory.

- `documented`: a page explains this message or its code and what to do about it.
- `partial`: the message or code appears, for example in a reference table, with no explanation of
  the cause or the fix.
- `none`: no occurrence outside the source.

Name the covering file for every `documented` and `partial` decision. A coverage claim without a
path is not evidence, and the formula treats `documented` as a hard zero, so an unsupported claim
silently deletes a real opportunity.
