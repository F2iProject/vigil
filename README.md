# Vigil

AI-powered, model-agnostic PR review with multi-persona specialist teams.

Vigil dispatches your pull request to a team of specialist reviewers — each focused on a single domain (security, logic, performance, etc.) — then a lead reviewer aggregates their verdicts into a final decision. Findings land as **inline PR comments** on the exact lines that need attention.

## How it works

```
PR Diff
  │
  ├─► Logic ──────────► findings
  ├─► Security ───────► findings
  ├─► Architecture ───► findings
  ├─► Testing ────────► findings
  ├─► Performance ────► findings
  └─► DX ─────────────► findings
                            │
                    Lead Reviewer
                            │
                  ┌─────────┴─────────┐
                  │  APPROVE / BLOCK  │
                  │  + inline comments│
                  └───────────────────┘
```

Each specialist only sees the files relevant to their domain (Security skips `.md` files, Testing focuses on test files + source, etc.). This keeps prompts focused and reduces token waste.

## Features

- **Model-agnostic** — runs on any LLM via [litellm](https://github.com/BerriAI/litellm) (Gemini, Claude, GPT, Mistral, local models, etc.)
- **Multi-persona review** — 6 specialist reviewers + lead, each with domain-scoped expertise
- **Inline PR comments** — findings posted directly on the diff lines, not buried in a wall of text
- **File-level routing** — each specialist only reviews files matching their domain patterns
- **Session IDs** — every specialist verdict is tagged with a unique ID (`VGL-a3f8b2`) for traceability
- **Structured output** — JSON mode with typed findings (severity, category, file, line, suggestion)
- **Built-in profiles** — `default` for general-purpose, `enterprise` for regulated/medtech (adds GxP, Data Architecture, tenant isolation)
- **GitHub Action** — drop into any repo's CI with 4 lines of YAML

## Quick start

```bash
pip install vigil-review
```

```bash
export GITHUB_TOKEN="ghp_..."
export GEMINI_API_KEY="..."  # or ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.

vigil review https://github.com/owner/repo/pull/123 --post
```

That's it. Vigil fetches the PR, runs all specialists, and posts a review with inline comments.

### CLI options

```
vigil review <PR_URL> [OPTIONS]

Options:
  -m, --model TEXT        LLM model (default: claude-sonnet-4-6)
  --lead-model TEXT       Different model for the lead reviewer
  -p, --profile TEXT      Review profile: default, enterprise
  --json                  Output raw JSON instead of pretty-printing
  --post                  Post review as GitHub PR review with inline comments
```

```bash
# Use Gemini Flash (fast + cheap)
vigil review https://github.com/org/repo/pull/42 -m gemini/gemini-2.5-flash --post

# Use Claude for lead, Gemini for specialists
vigil review https://github.com/org/repo/pull/42 -m gemini/gemini-2.5-flash --lead-model claude-sonnet-4-6 --post

# Enterprise profile (adds GxP, Data Architecture, tenant isolation reviewers)
vigil review https://github.com/org/repo/pull/42 -p enterprise --post

# JSON output for piping into other tools
vigil review https://github.com/org/repo/pull/42 --json
```

### List available profiles

```bash
vigil profiles
```

## GitHub Action

### Drop-in workflow (for your own repo)

```yaml
# .github/workflows/vigil-review.yml
name: Vigil PR Review
on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install vigil-review
      - env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          vigil review "${{ github.event.pull_request.html_url }}" \
            --model "gemini/gemini-2.5-flash" --post
```

### Reusable action

```yaml
- uses: F2iProject/vigil@main
  with:
    model: "gemini/gemini-2.5-flash"
    profile: "default"
    gemini-api-key: ${{ secrets.GEMINI_API_KEY }}
```

## Profiles

### `default` — 6 specialists + lead

| Specialist | Focus |
|---|---|
| **Logic** | Bugs, off-by-one, null handling, race conditions |
| **Security** | Injection, secrets, auth gaps, OWASP top 10 |
| **Architecture** | Coupling, API design, dependency direction |
| **Testing** | Coverage gaps, brittle tests, missing error path tests |
| **Performance** | N+1 queries, memory leaks, O(n²) on unbounded data |
| **DX** | Breaking changes, missing docs, confusing error messages |

### `enterprise` — 7 specialists + lead

Everything in `default`, plus:

| Specialist | Focus |
|---|---|
| **Data Architecture** | Schema design, migrations, indexes, entity ownership |
| **GxP Compliance** | Audit trails, ALCOA+, 21 CFR Part 11, immutability |

The enterprise profile also includes enhanced specialists with tenant isolation checks, cross-package impact analysis, and regulatory-aware reviews.

## How review decisions work

- **APPROVE** — all specialists pass, lead finds no blocking issues
- **REQUEST_CHANGES** — any specialist found critical/high severity issues
- **BLOCK** — lead found a fundamental problem (architectural violation, scope drift)

Each specialist operates under **domain sovereignty** — they only review their area and express constraints ("external input must be validated"), not implementation directives ("use Zod"). The lead reviewer mediates conflicts between specialists using a priority hierarchy: Regulatory > Security > Reliability > Convenience.

## Supported models

Anything [litellm supports](https://docs.litellm.ai/docs/providers):

```bash
# Google
vigil review $PR -m gemini/gemini-2.5-flash
vigil review $PR -m gemini/gemini-2.5-pro

# Anthropic
vigil review $PR -m claude-sonnet-4-6
vigil review $PR -m claude-opus-4

# OpenAI
vigil review $PR -m gpt-4o
vigil review $PR -m o3-mini

# Local (Ollama)
vigil review $PR -m ollama/llama3
```

Set the corresponding API key as an environment variable (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.).

## Architecture

```
src/vigil/
├── cli.py             # Typer CLI entry point
├── reviewer.py        # Multi-persona review engine
├── personas.py        # Specialist definitions & profiles
├── models.py          # Pydantic models (Finding, PersonaVerdict, ReviewResult)
├── diff_parser.py     # Diff parsing, file routing, commentable line extraction
├── github.py          # GitHub API (fetch PR data)
└── github_review.py   # Post reviews with inline comments
```

The review pipeline:

1. **Fetch** PR diff and metadata from GitHub
2. **Parse** diff into per-file hunks
3. **Route** each specialist to only their relevant files (via glob patterns)
4. **Dispatch** specialists sequentially (each gets a focused, smaller diff)
5. **Aggregate** verdicts and run lead reviewer
6. **Post** findings as inline PR comments on exact diff lines (with 3-layer fallback)

## License

[MIT](LICENSE)
