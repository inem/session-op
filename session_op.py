#!/usr/bin/env python3
"""
session-op - Turn chat conversations into frozen reusable CLI operators.
Freezes the entire message context from ChatGPT / Claude / TAP exports,
and exposes a CLI command that takes a new phrase and decomposes/transforms it
using the deep accumulated context of the session.

Backends:
  CLI (zero API tokens burned, uses CLI subscriptions):
    agy, claude, cursor, codex
  API (uses direct keys / per-token billing):
    openai, openrouter, anthropic
"""

import sys
import os
import re
import json
import argparse
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
import urllib.request
import urllib.error

# Avoid shadowing by local folders
if sys.path and sys.path[0] in ("", ".", os.getcwd()):
    sys.path.pop(0)

OPERATORS_DIR = Path.home() / ".config" / "tap-operators"
BIN_DIR = Path.home() / "bin"

CLI_BACKENDS = {"agy", "claude", "cursor", "codex"}
API_BACKENDS = {"openai", "openrouter", "anthropic"}

DEFAULT_INPUT_TEMPLATE = """# Selected text:

## Selection 1
{input}

## My request:
давай вот это разложим так же:"""


def parse_markdown_chat(content: str) -> list[dict]:
    """Parse TAP / ChatGPT / Claude markdown export into messages array."""
    pattern = re.compile(
        r'^(## (?:Вы|User|Пользователь|ChatGPT|Claude|Assistant|Ассистент))\s*$',
        re.MULTILINE
    )
    splits = pattern.split(content)
    
    messages = []
    for i in range(1, len(splits), 2):
        role_header = splits[i].strip()
        msg_body = splits[i+1].strip()
        
        # Strip leading timestamp <small>...</small>
        msg_body = re.sub(r'^<small>[^<]+</small>\s*', '', msg_body).strip()
        # Strip trailing markdown hr ---
        msg_body = re.sub(r'\s*---\s*$', '', msg_body).strip()
        
        is_user = any(w in role_header for w in ['Вы', 'User', 'Пользователь'])
        role = 'user' if is_user else 'assistant'
        
        if msg_body:
            messages.append({'role': role, 'content': msg_body})
            
    return messages


def parse_chatgpt_json(data: dict) -> list[dict]:
    """Parse ChatGPT raw session JSON into active branch messages array."""
    mapping = data.get('mapping', {})
    current_node = data.get('current_node')
    if not current_node or not mapping:
        return []
        
    chain = []
    curr = current_node
    while curr:
        chain.append(curr)
        node = mapping.get(curr, {})
        curr = node.get('parent')
        
    chain.reverse()
    messages = []
    for node_id in chain:
        msg = mapping[node_id].get('message')
        if not msg:
            continue
        role = msg.get('author', {}).get('role')
        if role not in ('user', 'assistant'):
            continue
            
        content = msg.get('content', {})
        parts = content.get('parts', [])
        text_parts = [p for p in parts if isinstance(p, str)]
        text = '\n'.join(text_parts).strip()
        
        if text and not text.startswith("Original custom instructions"):
            messages.append({'role': role, 'content': text})
            
    return messages


def load_chat_file(file_path: Path) -> list[dict]:
    """Load messages from file (.md or .json)."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
        
    text = file_path.read_text(encoding='utf-8')
    if file_path.suffix.lower() == '.json':
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'mapping' in data:
                return parse_chatgpt_json(data)
            elif isinstance(data, list):
                return data
        except Exception as e:
            raise ValueError(f"Failed to parse JSON: {e}")
            
    messages = parse_markdown_chat(text)
    if not messages:
        raise ValueError(f"Could not extract messages from {file_path}")
    return messages


def get_operator_path(name: str) -> Path:
    return OPERATORS_DIR / f"{name}.json"


def save_operator(operator_data: dict):
    OPERATORS_DIR.mkdir(parents=True, exist_ok=True)
    op_path = get_operator_path(operator_data["name"])
    with open(op_path, "w", encoding="utf-8") as f:
        json.dump(operator_data, f, ensure_ascii=False, indent=2)
        
    # Create launcher script in ~/bin
    if BIN_DIR.exists():
        bin_script = BIN_DIR / operator_data["name"]
        content = f"""#!/bin/sh
exec session-op run "{operator_data['name']}" "$@"
"""
        bin_script.write_text(content)
        bin_script.chmod(0o755)


def build_unified_prompt(messages: list[dict]) -> str:
    """Format full multi-turn conversation into a coherent prompt for CLI tools."""
    lines = [
        "Ниже приведена предшествующая беседа, в которой выработана алгебра операторов (recenter, reframe, fold, unfold, recognize) и нотация троек A -> B.",
        "Изучи контекст и выполни разбор нового утверждения в точности в таком же стиле, как в последних примерах диалога.\n",
        "---",
        "## История диалога:\n"
    ]
    
    # We include all messages except the last one (which is the new user turn)
    history = messages[:-1]
    new_turn = messages[-1]
    
    for m in history:
        prefix = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"[{prefix}]:\n{m['content']}\n")
        
    lines.append("---\n## Запрос пользователя:")
    lines.append(new_turn["content"])
    lines.append("\nРазложи это утверждение так же, как в примерах выше, используя формулы и шаги.")
    return "\n".join(lines)


# --- CLI Backend Invokers ---

def run_cli_backend(backend: str, messages: list[dict], model: str | None = None) -> str:
    """Run via local CLI subscription tools (zero API tokens burned)."""
    unified_prompt = build_unified_prompt(messages)
    
    cmd = []
    use_stdin = False
    
    if backend == "agy":
        cmd = ["agy", "-p", unified_prompt, "--output-format", "text"]
        if model:
            cmd.extend(["--model", model])
    elif backend == "claude":
        cmd = ["claude", "-p", "--output-format", "text"]
        if model:
            cmd.extend(["--model", model])
        use_stdin = True
    elif backend == "cursor":
        cmd = ["cursor-agent", "-p", "--trust", "--output-format", "text", "--mode", "ask", unified_prompt]
    elif backend == "codex":
        c_model = model or "o3-mini"
        cmd = ["codex", "exec", "-m", c_model, unified_prompt]
    else:
        raise ValueError(f"Unknown CLI backend: {backend}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if use_stdin else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout_data, stderr_data = proc.communicate(input=unified_prompt if use_stdin else None)
        
        if proc.returncode != 0:
            err_msg = stderr_data.strip() or stdout_data.strip()
            raise RuntimeError(f"{backend} exited with code {proc.returncode}: {err_msg}")
            
        sys.stdout.write(stdout_data)
        sys.stdout.flush()
        return stdout_data
    except FileNotFoundError:
        raise RuntimeError(f"CLI tool '{backend}' is not installed or not in PATH.")


# --- API Streaming Backends ---

def stream_openai_compatible(url: str, headers: dict, payload: dict) -> str:
    """Stream response from OpenAI-compatible SSE endpoints."""
    req = urllib.request.Request(
        url,
        headers=headers,
        data=json.dumps(payload).encode('utf-8')
    )
    full_output = []
    try:
        with urllib.request.urlopen(req) as resp:
            for line in resp:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    data_str = line[6:].strip()
                    if data_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get('choices')
                        if choices:
                            delta = choices[0].get('delta', {}).get('content', '')
                            if delta:
                                sys.stdout.write(delta)
                                sys.stdout.flush()
                                full_output.append(delta)
                    except Exception:
                        pass
        sys.stdout.write('\n')
        sys.stdout.flush()
        return ''.join(full_output)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"HTTP {e.code}: {err_body}")


def stream_anthropic(api_key: str, model: str, messages: list[dict], temperature: float) -> str:
    """Stream response from Anthropic API via SSE."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    system_text = ""
    filtered_msgs = []
    for m in messages:
        if m["role"] == "system":
            system_text += m["content"] + "\n\n"
        else:
            filtered_msgs.append({"role": m["role"], "content": m["content"]})
            
    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": temperature,
        "messages": filtered_msgs,
        "stream": True
    }
    if system_text:
        payload["system"] = system_text.strip()
        
    req = urllib.request.Request(url, headers=headers, data=json.dumps(payload).encode('utf-8'))
    full_output = []
    try:
        with urllib.request.urlopen(req) as resp:
            for line in resp:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    data_str = line[6:].strip()
                    try:
                        event = json.loads(data_str)
                        if event.get('type') == 'content_block_delta':
                            delta = event.get('delta', {}).get('text', '')
                            if delta:
                                sys.stdout.write(delta)
                                sys.stdout.flush()
                                full_output.append(delta)
                    except Exception:
                        pass
        sys.stdout.write('\n')
        sys.stdout.flush()
        return ''.join(full_output)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"Anthropic HTTP {e.code}: {err_body}")


def call_llm(messages: list[dict], model: str, backend: str, temperature: float = 0.7) -> str:
    """Route LLM call to appropriate CLI or API backend."""
    openai_key = os.environ.get("OPENAI_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    # If backend is a local CLI tool
    if backend in CLI_BACKENDS:
        return run_cli_backend(backend, messages, model if model != "gpt-4o" else None)

    # Resolve backend if auto
    if backend == "auto":
        if "/" in model:
            backend = "openrouter"
        elif "claude" in model and anthropic_key:
            backend = "anthropic"
        elif openai_key:
            backend = "openai"
        elif openrouter_key:
            backend = "openrouter"
        elif anthropic_key:
            backend = "anthropic"
        else:
            # Fallback to agy CLI if no API keys are present
            return run_cli_backend("agy", messages, model if model != "gpt-4o" else None)

    if backend == "openai":
        if not openai_key:
            raise ValueError("OPENAI_API_KEY is not set.")
        headers = {
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True
        }
        return stream_openai_compatible("https://api.openai.com/v1/chat/completions", headers, payload)

    elif backend == "openrouter":
        if not openrouter_key:
            raise ValueError("OPENROUTER_API_KEY is not set.")
        headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "User-Agent": "session-op/1.0",
            "HTTP-Referer": "https://github.com/session-op"
        }
        or_model = model
        if "/" not in or_model:
            if or_model.startswith("gpt") or or_model.startswith("o3") or or_model.startswith("o1"):
                or_model = f"openai/{or_model}"
            elif or_model.startswith("gemini"):
                or_model = f"google/{or_model}"
            elif or_model.startswith("claude"):
                or_model = f"anthropic/{or_model}"
                
        payload = {
            "model": or_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True
        }
        return stream_openai_compatible("https://openrouter.ai/api/v1/chat/completions", headers, payload)

    elif backend == "anthropic":
        if not anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY is not set.")
        return stream_anthropic(anthropic_key, model, messages, temperature)
    else:
        raise ValueError(f"Unknown backend: {backend}")


# --- CLI Commands ---

def cmd_freeze(args):
    file_path = Path(args.session_file).resolve()
    messages = load_chat_file(file_path)
    
    if args.up_to is not None:
        messages = messages[:args.up_to]
        
    name = args.name
    if not name:
        name = file_path.stem.split('.')[0]
        
    operator_data = {
        "name": name,
        "description": args.desc or f"Frozen session operator from {file_path.name}",
        "source_file": str(file_path),
        "created_at": datetime.now().isoformat(),
        "default_model": args.model or "gpt-4o",
        "default_backend": args.backend or "auto",
        "input_template": args.template or DEFAULT_INPUT_TEMPLATE,
        "message_count": len(messages),
        "messages": messages
    }
    
    save_operator(operator_data)
    print(f"✨ Operator '{name}' successfully created and frozen!")
    print(f"   Context: {len(messages)} messages ({sum(len(m['content']) for m in messages):,} chars)")
    print(f"   Source:  {file_path}")
    print(f"   Storage: {get_operator_path(name)}")
    if BIN_DIR.exists():
        print(f"   CLI Command: {BIN_DIR / name}")
        print(f"\nYou can now run:")
        print(f"   {name} \"ваша фраза для разбора\"")
        print(f"   echo \"фраза\" | {name}")


def cmd_run(args, unknown_args=None):
    name = args.operator_name
    op_path = get_operator_path(name)
    if not op_path.exists():
        print(f"Error: Operator '{name}' not found at {op_path}", file=sys.stderr)
        sys.exit(1)
        
    with open(op_path, "r", encoding="utf-8") as f:
        op_data = json.load(f)
        
    # Gather input text
    input_text = ""
    if args.phrase:
        parts = [args.phrase]
        if unknown_args:
            parts.extend(unknown_args)
        input_text = " ".join(parts).strip()
    elif not sys.stdin.isatty():
        input_text = sys.stdin.read().strip()
    else:
        try:
            input_text = input(f"{name} > ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
            
    if not input_text:
        print("Error: No input phrase provided.", file=sys.stderr)
        sys.exit(1)
        
    template = op_data.get("input_template", "{input}")
    if args.raw or "{input}" not in template or input_text.startswith("# Selected text:") or input_text.startswith("давай"):
        formatted = input_text
    else:
        formatted = template.format(input=input_text)
        
    full_messages = list(op_data["messages"])
    full_messages.append({"role": "user", "content": formatted})
    
    model = args.model or op_data.get("default_model", "gpt-4o")
    backend = args.backend or op_data.get("default_backend", "auto")
    
    try:
        output_text = call_llm(
            messages=full_messages,
            model=model,
            backend=backend,
            temperature=args.temperature
        )
        if args.copy and output_text:
            try:
                proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                proc.communicate(output_text.encode("utf-8"))
                print("\n📋 Copied to clipboard.", file=sys.stderr)
            except Exception:
                pass
    except Exception as e:
        print(f"\nExecution error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args):
    OPERATORS_DIR.mkdir(parents=True, exist_ok=True)
    files = list(OPERATORS_DIR.glob("*.json"))
    if not files:
        print("No operators found. Create one with: session-op freeze <session_path>")
        return
        
    print(f"{'OPERATOR':<20} {'MESSAGES':<10} {'MODEL':<18} {'BACKEND':<12} {'DESCRIPTION'}")
    print("-" * 85)
    for p in sorted(files):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            name = d.get("name", p.stem)
            msg_count = len(d.get("messages", []))
            model = d.get("default_model", "gpt-4o")
            backend = d.get("default_backend", "auto")
            desc = d.get("description", "")[:35]
            print(f"{name:<20} {msg_count:<10} {model:<18} {backend:<12} {desc}")
        except Exception:
            pass


def cmd_show(args):
    op_path = get_operator_path(args.operator_name)
    if not op_path.exists():
        print(f"Operator '{args.operator_name}' not found.", file=sys.stderr)
        sys.exit(1)
        
    with open(op_path, "r", encoding="utf-8") as f:
        d = json.load(f)
        
    print(f"Operator: {d.get('name')}")
    print(f"Description: {d.get('description')}")
    print(f"Source file: {d.get('source_file')}")
    print(f"Created: {d.get('created_at')}")
    print(f"Default model: {d.get('default_model')} ({d.get('default_backend')})")
    print(f"Messages count: {len(d.get('messages', []))}")
    print("\nTemplate:")
    print(d.get("input_template", "{input}"))
    print("\nMessage history overview:")
    for i, m in enumerate(d.get("messages", [])):
        preview = m['content'].replace('\n', ' ')[:80]
        print(f"  [{i:02d}] {m['role']:<10}: {preview}...")


def main():
    parser = argparse.ArgumentParser(
        description="session-op: freeze chat conversations into reusable CLI operators"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Command to run")
    
    all_backends = ["auto", "agy", "claude", "cursor", "codex", "openai", "openrouter", "anthropic"]

    # freeze
    p_freeze = subparsers.add_parser("freeze", help="Freeze a session file into an operator")
    p_freeze.add_argument("session_file", help="Path to markdown or json chat file")
    p_freeze.add_argument("-n", "--name", help="Name for the operator (e.g. triples)")
    p_freeze.add_argument("-d", "--desc", help="Short description")
    p_freeze.add_argument("-m", "--model", default="gpt-4o", help="Default model (default: gpt-4o)")
    p_freeze.add_argument("-b", "--backend", default="auto", choices=all_backends, help="Default backend")
    p_freeze.add_argument("--up-to", type=int, help="Freeze only first N messages")
    p_freeze.add_argument("--template", help="Custom prompt template containing {input}")

    # run
    p_run = subparsers.add_parser("run", help="Run a frozen operator")
    p_run.add_argument("operator_name", help="Name of operator to run")
    p_run.add_argument("phrase", nargs="?", help="Phrase/statement to decompose")
    p_run.add_argument("-m", "--model", help="Override LLM model")
    p_run.add_argument("-b", "--backend", choices=all_backends, help="Override backend (agy, claude, cursor, codex, openai, openrouter, anthropic)")
    p_run.add_argument("-t", "--temperature", type=float, default=0.7, help="Temperature")
    p_run.add_argument("--raw", action="store_true", help="Pass phrase directly without template wrapping")
    p_run.add_argument("-c", "--copy", action="store_true", help="Copy response to clipboard (pbcopy)")

    # list
    subparsers.add_parser("list", help="List all frozen operators")

    # show
    p_show = subparsers.add_parser("show", help="Show operator details")
    p_show.add_argument("operator_name", help="Name of operator")

    args, unknown = parser.parse_known_args()
    
    if args.subcommand == "freeze":
        cmd_freeze(args)
    elif args.subcommand == "run":
        cmd_run(args, unknown)
    elif args.subcommand == "list":
        cmd_list(args)
    elif args.subcommand == "show":
        cmd_show(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
