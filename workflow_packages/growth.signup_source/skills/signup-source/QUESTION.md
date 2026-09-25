# The question and its answers

One question, always optional, never preselected:

- Label: `How did you hear about us?`
- A choice list from `answer_options(signals)` below, in the order it returns.
- A short free-text box labelled `Anything more? (which podcast, who told you, what you asked)`,
  optional, at most 200 characters, always shown. Free text is what recovers the channels
  analytics files under "direct": a buyer who asked an AI assistant or heard it from a colleague
  types a new URL, and first-touch analytics never sees why.

Stored values: `signup_source` holds the chosen `value` (or nothing), `signup_source_detail`
holds the trimmed free text (or nothing). Never store the label; labels get reworded, values
must stay comparable across months.

The three core answers are always offered, because they are the channels a small company cannot
see any other way and the one it most often assumes. A channel beyond them is offered only with
evidence from this product: a path or URL showing the company actually uses it (a footer link to
its YouTube or subreddit, an ads pixel, a blog directory, a Tin report for that channel). A
channel the company does not use only adds noise to the list.

Collect `signals` as `{"signal": <key from CHANNELS>, "evidence": <path or URL>}`, then call
`answer_options(signals)` from the single Python block in this file, unchanged.

```python
CORE = (
    ("ai_assistant", "ChatGPT, Claude or another AI assistant"),
    ("search", "Google or another search engine"),
    ("friend", "A friend or colleague"),
)
# Evidence-backed channels, in the order they are offered when several apply.
CHANNELS = {
    "ads": ("ad", "An ad"),
    "outreach_email": ("email_from_us", "An email from us"),
    "blog": ("article", "An article or blog post"),
    "youtube": ("youtube", "YouTube"),
    "podcast": ("podcast", "A podcast"),
    "newsletter": ("newsletter", "A newsletter"),
    "reddit": ("reddit", "Reddit"),
    "hacker_news": ("hacker_news", "Hacker News"),
    "product_hunt": ("product_hunt", "Product Hunt"),
    "linkedin": ("linkedin", "LinkedIn"),
    "x": ("x", "X (Twitter)"),
    "github": ("github", "GitHub"),
    "event": ("event", "An event or talk"),
    "marketplace": ("marketplace", "An app store or marketplace"),
}
OTHER = ("other", "Somewhere else")
MAX_OPTIONS = 8


def answer_options(signals):
    if not isinstance(signals, list) or len(signals) > 64:
        raise ValueError("signals must be a list of at most 64 items")
    evidence = {}
    for item in signals:
        if not isinstance(item, dict) or set(item) != {"signal", "evidence"}:
            raise ValueError("each signal needs exactly signal and evidence")
        signal, proof = item["signal"], item["evidence"]
        if signal not in CHANNELS:
            raise ValueError(f"unknown signal {signal!r}")
        if not isinstance(proof, str) or not proof.strip() or len(proof) > 300:
            raise ValueError(f"signal {signal!r} needs a path or URL as evidence")
        evidence.setdefault(signal, proof.strip())
    options = [{"value": v, "label": label, "evidence": "core"} for v, label in CORE]
    room = MAX_OPTIONS - len(CORE) - 1
    for signal, (value, label) in CHANNELS.items():
        if signal in evidence and room > 0:
            options.append({"value": value, "label": label, "evidence": evidence[signal]})
            room -= 1
    options.append({"value": OTHER[0], "label": OTHER[1], "evidence": "core"})
    return options
```
