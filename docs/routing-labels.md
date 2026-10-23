# Routing labels

The scikit-learn baseline (M7) and the comparison against the LLM Router both need prompts that **people** have labeled. Never use model output as a label, because then we would be measuring the model against itself.

**Target:** at least 150 labeled prompts by the end of M2. At least 30 of them must be labeled independently by two people, so we can report agreement.

## File format

The file is a UTF-8 CSV with a header row:

```csv
prompt,request_type,complexity
Add a delete button to each todo item,code_edit,low
Why does the filter reset when I reload?,question,low
Replace Google login with GitHub OAuth and update the session handling,code_edit,high
```

- `split` is an optional column (`train` or `test`). Leave it out unless you have a reason. Each prompt then gets a stable 80/20 split computed from its text, so both labelers' copies of a prompt land in the same split.
- Write prompts the way a developer would type them into H.E.X Mind, about a to-do style web app or similar projects. Vary the phrasing and include some vague requests.

## Labels

**request_type**

| Value | Use when the developer… |
|---|---|
| `question` | wants an explanation, answer or analysis, and no files should change |
| `code_edit` | wants existing project files changed |
| `new_workflow` | wants a new feature, app or larger build that creates new code |
| `clarification` | is too vague to act on safely (for example "make it better" or "fix the thing") |

**complexity** (judge the work itself, not how long the prompt is)

| Value | Meaning | Example |
|---|---|---|
| `low` | one isolated, bounded change (one file, a few lines) | "Rename the Save button to Add" |
| `medium` | related changes across several files or components | "Add due dates to todos and show them in the list" |
| `high` | architectural, many dependencies, security-sensitive, or a broad refactor | "Add user accounts with password reset" |

When unsure between two levels, pick the higher one and note it in your own copy of the file. Don't discuss your labels with the other labeler until the agreement numbers have been computed.

## Commands

Run these from `apps/backend`:

```sh
uv run python -m app.evaluation.labels import ../../data/labels-raghav.csv --labeler raghav
uv run python -m app.evaluation.labels agreement raghav shrey   # Cohen's kappa on shared prompts
uv run python -m app.evaluation.labels stats
```

Re-importing a file replaces that labeler's labels for those prompts.

Report kappa together with raw agreement. A kappa below about 0.6 means the definitions above need tightening before the labels can be trusted.
