"""
agent_02_multiagent.py
=======================
Multi-Agent Orchestrator
  AI Foundry V2  ×  3-agent pipeline  ×  RBAC

Pipeline
--------
  User query
      │
      ▼
  [01] Router Agent          – routes to CODING or RAG specialist
      │
      ├── CODING_AGENT ──▶  [02a] Coding Agent  (CodeInterpreter)
      │                              │
      └── RAG_AGENT ────▶  [02b] RAG Agent     (AI Search / Robot-Joakim)
                                     │
                                     ▼
                           [03] Presenter Agent  (CodeInterpreter)
                                     │
                           • SOURCE=CODING → chart (bar/pie/line)
                           • SOURCE=RAG    → structured JSON

Authentication: DefaultAzureCredential (RBAC only – no account keys).

Sub-agent modules live in ./multi-agent/ and are loaded via importlib
(folder name contains a hyphen so standard import cannot be used directly).

Usage
-----
  python agent_02_multiagent.py
  python agent_02_multiagent.py --query "top 5 fruits by calorie"
  python agent_02_multiagent.py --query "How to reset Robot-Joakim?"
  python agent_02_multiagent.py --query "..." --no-cleanup
"""

import argparse
import importlib.util
import json
import os
import random
import re
import string
import sys
import time
from pathlib import Path

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    AzureAISearchQueryType,
    AgentsNamedToolChoice,
    AgentsNamedToolChoiceType,
    MessageRole,
)
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv

# ============================================================================
# Configuration  (mirrors agent_01_rag_test.py)
# ============================================================================

_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR.parent / ".env")


def _env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    return None if value == "<TODO>" else value


def _env_int(key: str, default: str | None = None) -> int | None:
    value = _env(key, default)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {key} must be an integer; got '{value}'") from exc


SUBSCRIPTION_ID          = _env("SUBSCRIPTION_ID", "<TODO>")
TENANT_ID                = _env("TENANT_ID", "<TODO>")
RESOURCE_GROUP           = _env("RESOURCE_GROUP", "<TODO>")

FOUNDRY_ACCOUNT_ENDPOINT = _env("FOUNDRY_ACCOUNT_ENDPOINT", "<TODO>")
FOUNDRY_PROJECT_ENDPOINT = _env("FOUNDRY_PROJECT_ENDPOINT", "<TODO>")

AI_SEARCH_NAME           = _env("AI_SEARCH_NAME", "<TODO>")
AI_SEARCH_ENDPOINT       = f"https://{AI_SEARCH_NAME}.search.windows.net"
AI_SEARCH_INDEX_NAME     = _env("AI_SEARCH_INDEX_NAME", "<TODO>")

CHAT_MODEL               = _env("CHAT_MODEL", "<TODO>")
EMBEDDING_MODEL          = _env("EMBEDDING_MODEL", "<TODO>")
EMBEDDING_DIMENSIONS     = _env_int("EMBEDDING_DIMENSIONS", "<TODO>")

DEFAULT_QUERY            = _env("DEFAULT_QUERY", "<TODO>")

# Output directory for CodeInterpreter chart images
OUTPUT_DIR               = Path(__file__).parent / "output"

# ============================================================================
# Load sub-agent modules from ./multi-agent/ via importlib
# ============================================================================

_MA_DIR = Path(__file__).parent / "multi-agent"


def _load_module(filename: str):
    """Load a Python file from the multi-agent/ directory by filename."""
    path = _MA_DIR / filename
    mod_name = filename.replace(".py", "").replace("-", "_")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


router_mod    = _load_module("01_router_agent_salt.py")
coding_mod    = _load_module("02a_coding_agent_salt.py")
rag_mod       = _load_module("02b_RAG_agent_salt.py")
presenter_mod = _load_module("03_presenter_agent.py")

# ============================================================================
# Helpers
# ============================================================================

def _make_salt(k: int = 5) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=k))


def _save_code_interpreter_files(
    agents_client: AgentsClient,
    thread_id: str,
    output_dir: Path,
) -> list[Path]:
    """Download any image files created by CodeInterpreter and save locally."""
    saved: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        for msg in agents_client.messages.list(thread_id=thread_id):
            if msg.role != MessageRole.AGENT:
                continue
            for part in (msg.content or []):
                text_part = getattr(part, "text", None)
                if not text_part:
                    continue
                for ann in (getattr(text_part, "annotations", None) or []):
                    fp = getattr(ann, "file_path", None)
                    if fp:
                        fid = fp.file_id
                        out = output_dir / f"{fid}.png"
                        chunks = agents_client.files.get_content(fid)
                        out.write_bytes(b"".join(chunks))
                        saved.append(out)
    except Exception as exc:
        print(f"    [warn] Could not download CodeInterpreter files: {exc}")
    return saved


def run_single_turn(
    agents_client: AgentsClient,
    agent,
    user_message: str,
    label: str = "",
    tool_choice=None,
    save_files: bool = False,
    output_dir: Path | None = None,
) -> tuple[str, list[Path]]:
    """
    Create a new thread, send one user message, run the agent (blocking),
    return (text_response, [saved_chart_paths]).

    The thread is deleted after the call.
    """
    thread = agents_client.threads.create()
    agents_client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=user_message,
    )

    run_kwargs: dict = {"thread_id": thread.id, "agent_id": agent.id}
    if tool_choice is not None:
        run_kwargs["tool_choice"] = tool_choice

    run = agents_client.runs.create_and_process(**run_kwargs)

    if run.status.value not in ("completed",):
        print(f"    {label}  run ended with status: {run.status}")

    # Collect text response
    last_msg = agents_client.messages.get_last_message_text_by_role(
        thread_id=thread.id, role=MessageRole.AGENT
    )
    text = last_msg.text.value if last_msg else ""

    # Collect annotations / citations
    annotations = []
    if last_msg:
        raw_anns = getattr(last_msg.text, "annotations", None) or []
        for ann in raw_anns:
            url_cit  = getattr(ann, "url_citation",  None)
            file_cit = getattr(ann, "file_citation", None)
            marker   = getattr(ann, "text", "")
            if url_cit:
                annotations.append(
                    f"  {marker}  {getattr(url_cit, 'title', '')}  "
                    f"{getattr(url_cit, 'url', '')}"
                )
            elif file_cit:
                annotations.append(
                    f"  {marker}  file_id={getattr(file_cit, 'file_id', '?')}"
                )

    # Download chart files if requested
    saved_files: list[Path] = []
    if save_files and output_dir:
        saved_files = _save_code_interpreter_files(
            agents_client, thread.id, output_dir
        )

    # Cleanup thread
    agents_client.threads.delete(thread.id)

    return text, annotations, saved_files


def _parse_json_route(router_text: str) -> tuple[str, str]:
    """
    Extract route and reason from the router agent's JSON response.
    Falls back to RAG_AGENT if parsing fails.
    """
    # Try strict JSON parse first
    try:
        data = json.loads(router_text.strip())
        return data.get("route", "RAG_AGENT"), data.get("reason", "")
    except json.JSONDecodeError:
        pass

    # Try to extract JSON object from within the text
    match = re.search(r'\{[^{}]*"route"[^{}]*\}', router_text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return data.get("route", "RAG_AGENT"), data.get("reason", "")
        except json.JSONDecodeError:
            pass

    # Heuristic fallback
    if "CODING" in router_text.upper():
        return "CODING_AGENT", "(heuristic)"
    return "RAG_AGENT", "(heuristic fallback)"


_PREFIXES = {
    "router":    None,   # filled from modules after load
    "coding":    None,
    "rag":       None,
    "presenter": None,
}


def find_existing_agent_sets(agents_client: AgentsClient) -> list[dict]:
    """
    Scan the project's agent list for complete sets of Router+Coding+RAG+Presenter
    agents sharing the same 5-char salt suffix.

    Returns a list of dicts, newest-first:
      [
        {"salt": "abc12",
         "router": <agent>, "coding": <agent>,
         "rag":    <agent>, "presenter": <agent>}
      ]
    """
    router_pfx    = router_mod.ROUTER_AGENT_NAME_PREFIX    + "-"
    coding_pfx    = coding_mod.CODING_AGENT_NAME_PREFIX    + "-"
    rag_pfx       = rag_mod.RAG_AGENT_NAME_PREFIX          + "-"
    presenter_pfx = presenter_mod.PRESENTER_AGENT_NAME_PREFIX + "-"

    by_salt: dict[str, dict] = {}
    try:
        for ag in agents_client.list_agents():
            name = getattr(ag, "name", "") or ""
            for pfx, key in [
                (router_pfx,    "router"),
                (coding_pfx,    "coding"),
                (rag_pfx,       "rag"),
                (presenter_pfx, "presenter"),
            ]:
                if name.startswith(pfx):
                    salt = name[len(pfx):]
                    bucket = by_salt.setdefault(salt, {})
                    bucket[key] = ag
                    break
    except Exception as exc:
        print(f"    [warn] Could not list agents: {exc}")
        return []

    # Only return complete sets (all 4 roles present)
    complete = [
        {"salt": s, **v}
        for s, v in by_salt.items()
        if all(k in v for k in ("router", "coding", "rag", "presenter"))
    ]
    return complete


def resolve_search_connection(project_client: AIProjectClient) -> str:
    """Return the AI Search connection name registered in the AI Foundry project."""
    try:
        for conn in project_client.connections.list():
            target    = getattr(conn, "target",   "") or ""
            conn_type = getattr(conn, "type",     "") or ""
            if AI_SEARCH_NAME in target.lower() or "cognitivesearch" in conn_type.lower():
                print(f"    Matched: name='{conn.name}'  target='{target}'")
                return conn.name
    except Exception as exc:
        print(f"    Warning – connection list failed: {exc}")
    print(f"    Fallback → {AI_SEARCH_NAME}")
    return AI_SEARCH_NAME


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    # ── CLI args ──────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description="Multi-Agent Orchestrator")
    parser.add_argument(
        "--query",
        default=None,
        help=f'User query (default: ask interactively; or "{DEFAULT_QUERY}")',
    )
    parser.add_argument(
        "--no-cleanup",
        dest="cleanup",
        action="store_false",
        default=None,
        help="Skip agent/thread deletion at the end",
    )
    parser.add_argument(
        "--new-agents",
        dest="new_agents",
        action="store_true",
        default=False,
        help="Always create new agents even if matching ones already exist",
    )
    args = parser.parse_args()

    # ── Banner ────────────────────────────────────────────────────────────
    print("=" * 68)
    print("  Multi-Agent Orchestrator")
    print("  Router → (CodingAgent | RAGAgent) → PresenterAgent")
    print("=" * 68)

    # ── Query ─────────────────────────────────────────────────────────────
    if args.query:
        user_query = args.query
    else:
        try:
            user_query = input(f'\nEnter your query (or press Enter for default):\n> ').strip()
            if not user_query:
                user_query = DEFAULT_QUERY
        except (EOFError, KeyboardInterrupt):
            user_query = DEFAULT_QUERY
    print(f'\n  Query: "{user_query}"')

    # ── Credentials ───────────────────────────────────────────────────────
    print("\n[1] DefaultAzureCredential (RBAC)…")
    credential = DefaultAzureCredential(
        additionally_allowed_tenants=[TENANT_ID],
        exclude_interactive_browser_credential=False,
    )

    # ── Clients ───────────────────────────────────────────────────────────
    print(f"\n[2] Connecting to AI Foundry project…")
    print(f"    {FOUNDRY_PROJECT_ENDPOINT}")
    project_client = AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=credential,
    )
    agents_client = AgentsClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=credential,
    )

    # ── AI Search connection ───────────────────────────────────────────────
    print("\n[3] Resolving AI Search connection…")
    search_connection_name = resolve_search_connection(project_client)

    # ── Check for existing agent sets ────────────────────────────────────
    print("\n[4] Checking for existing agents…")
    existing_sets = find_existing_agent_sets(agents_client)

    reuse_set: dict | None = None

    if existing_sets and not args.new_agents:
        print(f"    Found {len(existing_sets)} existing complete set(s):")
        for es in existing_sets:
            s = es["salt"]
            print(
                f"      salt='{s}'  "
                f"router={es['router'].id}  "
                f"coding={es['coding'].id}  "
                f"rag={es['rag'].id}  "
                f"presenter={es['presenter'].id}"
            )
        try:
            ans = input("\nCreate new agents? (y/n): ").strip().lower()
            create_new = ans == "y"
        except (EOFError, KeyboardInterrupt):
            create_new = True
            print("\nCreate new agents: yes (non-interactive default)")

        if not create_new:
            reuse_set = existing_sets[0]   # reuse the first (most recently found) set
            salt = reuse_set["salt"]
            print(f"    Reusing agent set with salt='{salt}'")
        else:
            print("    Creating fresh agents…")
    elif args.new_agents:
        print("    --new-agents flag set: creating fresh agents.")
    else:
        print("    No existing sets found: creating fresh agents.")

    # ── Create or reuse agents ────────────────────────────────────────────
    if reuse_set:
        router_agent    = reuse_set["router"]
        coding_agent    = reuse_set["coding"]
        rag_agent       = reuse_set["rag"]
        presenter_agent = reuse_set["presenter"]
        router_name    = router_agent.name
        coding_name    = coding_agent.name
        rag_name       = rag_agent.name
        presenter_name = presenter_agent.name
        print(f"    [01] {router_name}       id={router_agent.id}")
        print(f"    [02a] {coding_name}      id={coding_agent.id}")
        print(f"    [02b] {rag_name}         id={rag_agent.id}")
        print(f"    [03] {presenter_name}  id={presenter_agent.id}")
    else:
        salt = _make_salt(5)
        print(f"    Generating new salt='{salt}'…")
        router_name    = f"{router_mod.ROUTER_AGENT_NAME_PREFIX}-{salt}"
        coding_name    = f"{coding_mod.CODING_AGENT_NAME_PREFIX}-{salt}"
        rag_name       = f"{rag_mod.RAG_AGENT_NAME_PREFIX}-{salt}"
        presenter_name = f"{presenter_mod.PRESENTER_AGENT_NAME_PREFIX}-{salt}"

        router_agent = router_mod.create_agent(
            agents_client, CHAT_MODEL, router_name
        )
        print(f"    [01] {router_name}       id={router_agent.id}")

        coding_agent = coding_mod.create_agent(
            agents_client, CHAT_MODEL, coding_name
        )
        print(f"    [02a] {coding_name}      id={coding_agent.id}")

        rag_agent = rag_mod.create_agent(
            agents_client, CHAT_MODEL, rag_name,
            search_connection_name=search_connection_name,
            search_index_name=AI_SEARCH_INDEX_NAME,
        )
        print(f"    [02b] {rag_name}         id={rag_agent.id}")

        presenter_agent = presenter_mod.create_agent(
            agents_client, CHAT_MODEL, presenter_name
        )
        print(f"    [03] {presenter_name}  id={presenter_agent.id}")

    # ── Step 1: Route ─────────────────────────────────────────────────────
    print(f"\n[5] Router Agent → routing query…")
    router_text, _, _ = run_single_turn(
        agents_client=agents_client,
        agent=router_agent,
        user_message=user_query,
        label="[router]",
    )
    print(f"    Raw router response: {router_text.strip()[:200]}")

    route, reason = _parse_json_route(router_text)
    print(f"    Route: {route}  ({reason})")

    # ── Step 2: Specialist ────────────────────────────────────────────────
    specialist_text: str = ""
    specialist_annotations: list[str] = []
    chart_files: list[Path] = []

    if route == "CODING_AGENT":
        print(f"\n[6] Coding Agent → running code interpreter…")
        specialist_text, specialist_annotations, chart_files = run_single_turn(
            agents_client=agents_client,
            agent=coding_agent,
            user_message=user_query,
            label="[02a_coding]",
            save_files=True,
            output_dir=OUTPUT_DIR,
        )
        print(f"    Specialist response ({len(specialist_text)} chars)")
        if chart_files:
            print(f"    Charts saved: {[str(f) for f in chart_files]}")
    else:
        print(f"\n[6] RAG Agent → querying AI Search…")
        specialist_text, specialist_annotations, _ = run_single_turn(
            agents_client=agents_client,
            agent=rag_agent,
            user_message=user_query,
            label="[02b_rag]",
            tool_choice=AgentsNamedToolChoice(
                type=AgentsNamedToolChoiceType.AZURE_AI_SEARCH
            ),
        )
        print(f"    Specialist response ({len(specialist_text)} chars)")
        if specialist_annotations:
            print("    Citations:")
            for a in specialist_annotations:
                print(f"      {a}")

    # ── Step 3: Presenter ─────────────────────────────────────────────────
    print(f"\n[7] Presenter Agent → formatting output (SOURCE={route})…")

    # Build presenter prompt: include source tag + specialist output
    chart_context = ""
    if chart_files:
        chart_context = (
            f"\n\nNote: The coding agent also saved {len(chart_files)} chart file(s). "
            "Please recreate a polished version using your own code_interpreter."
        )

    presenter_prompt = (
        f"SOURCE={route}\n\n"
        f"ORIGINAL USER QUESTION:\n{user_query}\n\n"
        f"SPECIALIST AGENT RESPONSE:\n{specialist_text}"
        f"{chart_context}"
    )

    presenter_text, _, presenter_charts = run_single_turn(
        agents_client=agents_client,
        agent=presenter_agent,
        user_message=presenter_prompt,
        label="[03_presenter]",
        save_files=(route == "CODING_AGENT"),
        output_dir=OUTPUT_DIR,
    )

    # ── Final output ──────────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print(f"  FINAL OUTPUT  (formatted by Presenter Agent | route={route})")
    print("=" * 68)

    if route == "RAG_AGENT":
        # Try to pretty-print as JSON
        raw = presenter_text.strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                print(json.dumps(parsed, indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                print(raw)
        else:
            print(raw)
    else:
        # Coding: print text + chart file paths
        print(presenter_text)
        all_charts = chart_files + presenter_charts
        if all_charts:
            print("\nChart file(s) saved:")
            for p in all_charts:
                print(f"  {p}")

    print("=" * 68)

    # ── Cleanup ───────────────────────────────────────────────────────────
    if args.cleanup is None:
        # Interactive
        try:
            ans = input(
                "\nWould you like to delete all agents and clean up? (y/n): "
            ).strip().lower()
            do_cleanup = ans == "y"
        except (EOFError, KeyboardInterrupt):
            do_cleanup = True
            print("\nCleanup: yes (non-interactive default)")
    else:
        do_cleanup = args.cleanup

    if do_cleanup:
        print("\n[8] Cleaning up agents…")
        all_agents = [
            (router_agent,    router_name),
            (coding_agent,    coding_name),
            (rag_agent,       rag_name),
            (presenter_agent, presenter_name),
        ]
        for ag, name in all_agents:
            try:
                agents_client.delete_agent(ag.id)
                print(f"    Deleted: {name}  ({ag.id})")
            except Exception as exc:
                print(f"    Warn – could not delete {name}: {exc}")
    else:
        print("\n[8] Skipping cleanup. Agent IDs:")
        print(f"    [01] {router_name}       {router_agent.id}")
        print(f"    [02a] {coding_name}      {coding_agent.id}")
        print(f"    [02b] {rag_name}         {rag_agent.id}")
        print(f"    [03] {presenter_name}  {presenter_agent.id}")

    print("\nDone ✓")


if __name__ == "__main__":
    main()
