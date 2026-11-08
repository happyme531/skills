#!/usr/bin/env python3
"""Search bounded local coding-agent memory stores using ripgrep."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit


AGENTS = ("codex", "claude", "antigravity", "grok")


@dataclass(frozen=True)
class Source:
    agent: str
    scope: str
    kind: str
    path: Path
    candidate: bool = False
    knowledge_metadata: bool = False


def git_value(project: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project), *args], capture_output=True,
            text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def project_hints(project: Path | None) -> tuple[set[str], set[str], list[Path]]:
    if project is None:
        return set(), set(), []
    project = project.expanduser().resolve()
    paths = [project]
    top = git_value(project, "rev-parse", "--show-toplevel")
    if top:
        paths.append(Path(top).resolve())
        common = git_value(project, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common and Path(common).name == ".git":
            paths.append(Path(common).parent.resolve())
    paths = list(dict.fromkeys(paths))
    claude_keys = {re.sub(r"[^A-Za-z0-9]", "-", str(path)) for path in paths}
    special = os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME")
    if special:
        claude_keys.add(special)
    names = {path.name for path in paths}
    remote = git_value(project, "config", "--get", "remote.origin.url")
    if remote:
        # Only derive the repository basename; do not print remotes or credentials.
        path = urlsplit(remote).path if "://" in remote else remote.rsplit(":", 1)[-1]
        names.add(path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))
    slugs = {re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", n.lower()))[:40].strip("-") for n in names}
    return claude_keys, slugs - {""}, paths


def custom_claude_memory(settings: Path) -> Path | None:
    try:
        value = json.loads(settings.read_text(encoding="utf-8")).get("autoMemoryDirectory")
        if isinstance(value, str) and (value.startswith("~/") or Path(value).is_absolute()):
            return Path(value).expanduser()
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        pass
    return None


def children(path: Path) -> list[Path]:
    try:
        return sorted((p for p in path.iterdir() if p.is_dir()), key=lambda p: p.name)
    except OSError:
        return []


def discover(args: argparse.Namespace) -> list[Source]:
    home = Path.home()
    codex = Path(args.codex_home or os.environ.get("CODEX_HOME") or home / ".codex").expanduser()
    claude = Path(args.claude_home or os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude").expanduser()
    grok = Path(args.grok_home or os.environ.get("GROK_HOME") or home / ".grok").expanduser()
    agy = Path(args.agy_home or home / ".gemini/antigravity-cli").expanduser()
    keys, slugs, project_paths = project_hints(args.project)
    sources: list[Source] = []

    def add(agent: str, scope: str, kind: str, path: Path, candidate: bool = False,
            knowledge_metadata: bool = False) -> None:
        if path.exists():
            sources.append(Source(agent, scope, kind, path, candidate, knowledge_metadata))

    add("codex", "mixed", "native-index", codex / "memories/MEMORY.md")

    add("claude", "global", "instructions", claude / "CLAUDE.md")
    add("claude", "global", "rules", claude / "rules")
    add("claude", "global", "subagent-memory", claude / "agent-memory")
    for entry in children(claude / "projects"):
        add("claude", "project", "auto-memory", entry / "memory", entry.name in keys)
    settings = [claude / "settings.json"]
    for project in project_paths:
        for path in (project / "CLAUDE.md", project / "CLAUDE.local.md",
                     project / ".claude/CLAUDE.md", project / ".claude/CLAUDE.local.md"):
            add("claude", "project", "instructions", path, True)
        add("claude", "project", "rules", project / ".claude/rules", True)
        add("claude", "project", "subagent-memory", project / ".claude/agent-memory", True)
        settings.extend((project / ".claude/settings.json", project / ".claude/settings.local.json"))
    for setting in settings:
        custom = custom_claude_memory(setting)
        if custom:
            add("claude", "mixed", "custom-auto-memory", custom, setting != settings[0])

    def add_agy(root: Path, prefix: str) -> None:
        add("antigravity", "mixed", prefix + "knowledge", root / "knowledge", knowledge_metadata=True)
        if not args.no_artifacts:
            add("antigravity", "mixed", prefix + "artifact", root / "brain")

    add_agy(agy, "")
    if args.include_antigravity_desktop:
        add_agy(home / ".gemini/antigravity", "desktop-")

    v2 = grok / "memory-v2"
    add("grok", "global", "v2-memory", v2 / "global")
    for entry in children(v2 / "workspaces"):
        name, _, suffix = entry.name.rpartition("-")
        candidate = name in slugs and bool(re.fullmatch(r"[0-9a-fA-F]{8}", suffix))
        add("grok", "project", "v2-memory", entry, candidate)
    legacy = grok / "memory"
    add("grok", "global", "legacy-memory", legacy / "MEMORY.md")
    for entry in children(legacy):
        name, _, suffix = entry.name.rpartition("-")
        candidate = name in slugs and bool(re.fullmatch(r"[0-9a-fA-F]{8}", suffix))
        add("grok", "project", "legacy-memory", entry, candidate)

    chosen = set(args.agent or AGENTS)
    sources = [s for s in sources if s.agent in chosen and
               (args.scope == "all" or s.scope in (args.scope, "mixed"))]
    # A matching project key is only a hint; retain other project stores to avoid silent misses.
    order = {agent: i for i, agent in enumerate(AGENTS)}
    sources.sort(key=lambda s: (order[s.agent], 0 if s.candidate else 1, str(s.path)))
    return list(dict.fromkeys(sources))


def decoded(field: dict) -> str:
    if "text" in field:
        return field["text"]
    return os.fsdecode(base64.b64decode(field.get("bytes", "")))


def describe(source: Source, path: str) -> str:
    kind = source.kind
    normalized = path.replace(os.sep, "/")
    if source.agent == "grok" and source.kind == "v2-memory":
        if "/observations/_inbox/" in normalized:
            kind = "v2-pending-observation"
        elif "/archive/" in normalized:
            kind = "v2-archived-observation"
        elif "/topics/" in normalized:
            kind = "v2-topic"
        elif Path(path).name == "MEMORY.md":
            kind = "v2-index"
        elif not Path(path).is_dir():
            kind = "v2-note"
    relation = "candidate" if source.candidate else ("unverified" if source.scope != "global" else "global")
    return f"{source.agent} | {source.scope} | {kind} | {relation}"


def search_source(source: Source, queries: list[str], limit: int, include_archives: bool) -> tuple[int, bool, str | None]:
    cmd = ["rg", "--json", "--no-config", "--hidden", "--no-ignore",
           "--ignore-case", "--fixed-strings", "--glob", "*.md"]
    if source.knowledge_metadata:
        cmd += ["--glob", "metadata.json"]
    cmd += ["--glob", "!**/.system_generated/**"]
    if not include_archives:
        cmd += ["--glob", "!**/archive/**"]
    for query in queries:
        cmd += ["-e", query]
    cmd += ["--", str(source.path)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        return 0, False, str(exc)
    count, capped = 0, False
    assert proc.stdout is not None
    for line in proc.stdout:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "match":
            continue
        if count >= limit:
            capped = True
            proc.terminate()
            break
        data = obj["data"]
        path = decoded(data["path"])
        content = decoded(data["lines"]).strip().replace("\n", " ")
        if len(content) > 400:
            content = content[:400] + "…"
        print(f"[{describe(source, path)}] {path}:{data['line_number']}: {content}")
        count += 1
    proc.stdout.close()
    stderr = proc.stderr.read().strip() if proc.stderr else ""
    result = proc.wait()
    if not capped and result not in (0, 1):
        return count, False, stderr or f"rg exited {result} while searching {source.path}"
    return count, capped, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", "-q", action="append", help="literal case-insensitive keyword; repeat for OR")
    parser.add_argument("--agent", choices=AGENTS, action="append", help="restrict providers; repeatable")
    parser.add_argument("--scope", choices=("all", "global", "project"), default="all", help="mixed-scope stores are always included")
    parser.add_argument("--project", type=Path, help="prioritize possible project stores; does not filter or prove identity")
    parser.add_argument("--max-hits", type=int, default=30, help="maximum matching lines per provider (default: 30)")
    parser.add_argument("--list-sources", action="store_true", help="list existing stores instead of searching")
    parser.add_argument("--include-archives", action="store_true", help="include archived Grok observations")
    parser.add_argument("--no-artifacts", action="store_true", help="exclude Antigravity conversation artifacts")
    parser.add_argument("--include-antigravity-desktop", action="store_true", help="also search the separate desktop/IDE store")
    parser.add_argument("--codex-home", help="override Codex home")
    parser.add_argument("--claude-home", help="override Claude config directory")
    parser.add_argument("--grok-home", help="override Grok home")
    parser.add_argument("--agy-home", help="override Antigravity CLI data directory")
    args = parser.parse_args()
    if args.max_hits < 1:
        parser.error("--max-hits must be positive")
    if not args.list_sources and not args.query:
        parser.error("provide at least one --query or use --list-sources")
    if args.query and any(not q.strip() or "\n" in q or "\r" in q for q in args.query):
        parser.error("queries must be nonempty single-line strings")
    if not args.list_sources and not shutil.which("rg"):
        parser.error("ripgrep (rg) is required")
    sources = discover(args)
    providers = [a for a in AGENTS if a in set(args.agent or AGENTS)]
    if args.list_sources:
        for source in sources:
            print(f"[{describe(source, str(source.path))}] {source.path}")
        for agent in providers:
            if not any(s.agent == agent for s in sources):
                print(f"[{agent}] no accessible default/configured source found")
        return 0
    failed = False
    for agent in providers:
        group = [s for s in sources if s.agent == agent]
        if not group:
            print(f"[{agent}] no accessible default/configured source found")
            continue
        count, capped = 0, False
        for source in group:
            if count >= args.max_hits:
                capped = True
                break
            found, partial, error = search_source(source, args.query, args.max_hits - count, args.include_archives)
            count += found
            capped |= partial
            if error:
                print(f"[{agent}] search error: {error}", file=sys.stderr)
                failed = True
            if capped:
                break
        suffix = "; capped, narrow query or increase --max-hits" if capped else ""
        print(f"[{agent}] {count} matching lines, {len(group)} available source(s){suffix}")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
