# session-op

Turn rich chat conversations into frozen, reusable, pipeable CLI operators.

```
       [ Long interactive chat: terminology, nuance, few-shots ]
                                 │
                                 ▼
                     session-op freeze chat.md -n decompose
                                 │
                                 ▼
           echo "new concept" | decompose | critic | codegen
```

---

## The Idea

A great dialogue with an LLM often develops a unique domain language, agreed-upon invariants, and nuanced decomposition schemas. Once the conversation reaches its peak, starting over in a new prompt loses all the accumulated context.

`session-op` extracts and freezes the entire multi-turn message history (`user` ↔ `assistant`) into an immutable **operator**: a standalone Unix CLI command that takes a new phrase and processes it through the lens of that frozen conversation.

Every operator is a standard Unix filter (`stdin → stdout`), meaning you can chain multiple frozen dialogues into transformation pipelines:

$$ \text{RawIdea} \xrightarrow{\text{triples}} \text{Decomposition} \xrightarrow{\text{critic}} \text{WeakSpots} \xrightarrow{\text{synthesize}} \text{Architecture} $$

---

## Features

- **Frozen Context**: Parses TAP / ChatGPT / Claude markdown exports or raw ChatGPT JSON sessions into clean multi-turn dialogue arrays.
- **Instant CLI Commands**: Freezing a session instantly creates a standalone executable in `~/bin/<name>` (e.g. `triples "your phrase"`).
- **Zero API Tokens via Local CLI Subscriptions**:
  Run through your existing command-line subscriptions without paying API tokens:
  - `agy` (Antigravity CLI)
  - `claude` (Claude Code CLI via Claude Pro/Max)
  - `cursor` (`cursor-agent` via Cursor subscription)
  - `codex` (`codex exec` via Codex CLI)
- **Direct API Streaming**:
  Built-in zero-dependency SSE streaming for `openai`, `openrouter`, and `anthropic`.
- **Pure Unix Pipeability**:
  Accepts input as CLI arguments, through standard input (`|`), or interactively.
- **Zero External Dependencies**:
  Runs on pure Python 3 using standard library network and subprocess modules (instant startup, 0ms overhead).

---

## Installation

```bash
git clone https://github.com/inem/session-op.git
cd session-op
./install.sh
```

Ensure `~/bin` is in your `$PATH`:
```bash
export PATH="$HOME/bin:$PATH"
```

---

## Quickstart

### 1. Freeze a chat into an operator

Point `session-op freeze` at any exported chat (Markdown or JSON):

```bash
session-op freeze ~/path/to/chat.md --name triples --desc "Decomposes statements into triples A -> B"
```

This creates:
- The operator payload at `~/.config/tap-operators/triples.json`
- An executable launcher command at `~/bin/triples`

### 2. Run the operator

```bash
# As a CLI argument
triples "A pipeline in unix style is a composition of folds and unfolds"

# Via pipe (stdin)
echo "An interface is an agreement on valid state folds" | triples

# From clipboard
pbpaste | triples

# Interactive prompt
triples
```

### 3. Chain operators in pipelines

```bash
echo "Database is a materialized view of an append-only event log" \
  | triples \
  | critic \
  | codegen > output.ts
```

---

## Backends: Local CLI vs API

You can switch the execution engine on the fly:

### 1. Local CLI Subscriptions (0 API Tokens)

```bash
# Antigravity CLI (fast, local)
triples -b agy "Your concept"

# Claude Code CLI (Claude subscription)
triples -b claude "Your concept"

# Cursor Agent CLI
triples -b cursor "Your concept"

# Codex CLI
triples -b codex "Your concept"
```

### 2. Direct API with Streaming

Set your API keys (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, or `ANTHROPIC_API_KEY`):

```bash
# OpenAI GPT-4o / o3-mini
triples -b openai -m gpt-4o "Your concept"
triples -b openai -m o3-mini "Your concept"

# Any OpenRouter model (Claude, Gemini, DeepSeek)
triples -b openrouter -m anthropic/claude-3.7-sonnet "Your concept"
triples -b openrouter -m google/gemini-2.5-pro "Your concept"
```

---

## CLI Reference

### `session-op freeze`
```bash
session-op freeze <chat_file> [options]

Options:
  -n, --name <name>        Name of the command to create (default: filename stem)
  -d, --desc <desc>        Short description
  -b, --backend <backend>  Default backend: auto, agy, claude, cursor, codex, openai, openrouter, anthropic
  -m, --model <model>      Default model (e.g. gpt-4o, claude-3-7-sonnet)
  --up-to <N>              Freeze only the first N messages of the conversation
  --template <tmpl>        Input template with {input} placeholder
```

### `session-op list`
List all registered frozen operators:
```bash
session-op list
```

### `session-op show`
Inspect the message history and template of an operator:
```bash
session-op show triples
```

### `session-op run`
```bash
session-op run <name> [phrase] [options]

Options:
  -b, --backend <backend>  Override backend (agy, claude, cursor, codex, openai, openrouter, anthropic)
  -m, --model <model>      Override model
  -t, --temperature <t>   Temperature (default: 0.7)
  --raw                    Do not wrap input into template, pass as-is
  -c, --copy               Copy output to clipboard via pbcopy
```

---

## License

MIT © [inem](https://github.com/inem)
