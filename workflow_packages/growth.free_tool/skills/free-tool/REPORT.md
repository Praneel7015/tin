# Report contract

Write Markdown to context.output.path. Keep the whole report under 12000 characters.
Plain, specific sentences; no marketing adjectives; no invented numbers.

Start with exactly these header lines:

    # Free tool pick
    Status: complete
    Product: <product_url>
    Verdict: <one sentence naming the winning tool, or "No tool worth building">

Status is complete or incomplete, per SKILL.md step 6. Then use these headings in order.

## The buyer
Three lines: what the product does, who pays, the recurring job the tool would serve.
Cite the product page URL and any repository path:line used. Then one line listing the
free tools the company already offers, with URLs or path:line, or "None found".

## Pick
Write "None. <one-sentence reason>" when there is no winner. Otherwise, for the one winner:

- Tool: a plain name and one sentence on what a visitor puts in and gets out.
- Target phrase: the phrase, its demand label, its winnability label, and the result URLs
  that support both labels.
- Existing free tools and the gap: up to four URLs, each with its observed weakness, then
  the single gap this tool fixes.
- Built from: the path:line references that already do the core work, or "Written fresh"
  with what must be written, and the build effort label with one sentence of justification.
- Minimal spec: inputs, outputs, what runs in the browser or server, and what stays gated
  behind the product.
- Path to the product: the step after the tool's result where a visitor needs the product.
- Upkeep: hosting, per-use cost, abuse or rate-limit exposure, and maintenance in plain words.
- Score: path, gap, demand, build and upkeep values and the total.
- Check after 60 days: one signal the founder can read in their own analytics (for example
  search visits to the tool page and signups that started there) and a stop rule stated as
  a comparison against it. Do not predict what the number will be.

## Runners-up
The two best other survivors get one paragraph each: tool, phrase, labels, score and why
it lost. Any further survivors get one line each. Write "None." when there are none.

## Rejected
One line per rejected candidate: phrase or idea, the veto or "score below 6", and the
evidence URL or path:line.

## Next steps
Two pointers, not actions taken:

- A ready-to-paste instruction for a one-off project task that builds the winning tool as a
  single page, naming the files from "Built from", the spec and what must not be exposed.
- "Run Plan keyword opportunities with these seed phrases: ..." so real search volume can
  confirm the demand labels.

Write "None." for the first pointer when there is no winner; still give seed phrases if any
phrase had demand.

## What this run did not check
Anything the budget, an unreadable page or the repository snapshot left unverified.
