#!/usr/bin/env python3
"""Search local coding-agent transcripts and Antigravity SQLite payloads."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from urllib.parse import unquote


AGENTS = ("codex", "claude", "antigravity", "grok")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


@dataclass(frozen=True)
class Source:
    agent: str
    kind: str
    path: Path
    session: str
    hint: str = ""


def rg_files(root: Path) -> tuple[list[Path], str | None]:
    if not root.is_dir():
        return [], None
    try:
        p = subprocess.run(["rg", "--files", "--hidden", "--no-ignore", "--null", "--", str(root)],
                           capture_output=True, check=False)
    except OSError as e:
        return [], str(e)
    if p.returncode not in (0, 1):
        return [], os.fsdecode(p.stderr).strip() or f"rg exited {p.returncode}"
    return [Path(os.fsdecode(x)) for x in p.stdout.split(b"\0") if x], None


def read_json_lines(path: Path, maximum: int | None = None):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for number, line in enumerate(f, 1):
                if maximum is not None and number > maximum:
                    break
                try:
                    yield number, json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def agy_workspaces(home: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for _, obj in read_json_lines(home / "history.jsonl"):
        if isinstance(obj, dict) and isinstance(obj.get("conversationId"), str) and isinstance(obj.get("workspace"), str):
            result.setdefault(obj["conversationId"], set()).add(obj["workspace"])
    return result


def session_from_path(agent: str, path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    if agent == "antigravity":
        return rel.parts[0] if root.name == "brain" else path.stem
    if agent == "grok" and len(rel.parts) >= 3:
        return rel.parts[1]
    if agent == "claude" and "subagents" in rel.parts:
        i = rel.parts.index("subagents")
        return rel.parts[i - 1] + "/" + path.stem if i else path.stem
    match = UUID_RE.findall(path.name)
    return match[-1] if match else path.stem


def sources(args: argparse.Namespace) -> tuple[list[Source], list[str], list[Path]]:
    home = Path.home()
    codex = Path(args.codex_home or os.environ.get("CODEX_HOME") or home / ".codex").expanduser()
    claude = Path(args.claude_home or os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude").expanduser()
    agy = Path(args.agy_home or home / ".gemini/antigravity-cli").expanduser()
    grok = Path(args.grok_home or os.environ.get("GROK_HOME") or home / ".grok").expanduser()
    selected = set(args.agent or AGENTS)
    found: list[Source] = []
    issues: list[str] = []
    opaque: list[Path] = []
    roots = []
    if "codex" in selected:
        roots += [("codex", "sessions", codex / "sessions"), ("codex", "archive", codex / "archived_sessions")]
    if "claude" in selected:
        roots.append(("claude", "transcript", claude / "projects"))
    if "antigravity" in selected:
        roots.append(("antigravity", "brain", agy / "brain"))
    if "grok" in selected:
        roots.append(("grok", "sessions", grok / "sessions"))
    for agent, root_kind, root in roots:
        paths, error = rg_files(root)
        if error:
            issues.append(f"{agent}: cannot enumerate {root}: {error}")
        for path in paths:
            kind = root_kind
            rel = path.relative_to(root)
            if agent in ("codex", "claude"):
                if not path.name.endswith((".jsonl", ".jsonl.gz", ".jsonl.zst")):
                    continue
            elif agent == "grok":
                if path.name in ("updates.jsonl", "chat_history.jsonl") and len(rel.parts) == 3:
                    kind = path.stem
                elif len(rel.parts) >= 4 and "terminal" in rel.parts and path.suffix == ".log":
                    kind = "terminal-output"
                else:
                    continue
            else:
                if len(rel.parts) < 4 or ".system_generated" not in rel.parts:
                    continue
                if path.name in ("transcript.jsonl", "transcript_full.jsonl") and "logs" in rel.parts:
                    kind = "transcript"
                elif path.suffix == ".jsonl" and "chunks" in rel.parts and "logs" in rel.parts:
                    kind = "transcript-chunk"
                elif path.name == "output.txt" and "steps" in rel.parts:
                    kind = "tool-output"
                else:
                    continue
            session = session_from_path(agent, path, root)
            hint = unquote(rel.parts[0]) if agent == "grok" and rel.parts else ""
            if agent == "grok" and hint and not hint.startswith("/"):
                try:
                    hint = (root / rel.parts[0] / ".cwd").read_text(encoding="utf-8").strip()
                except OSError:
                    hint = ""
            found.append(Source(agent, kind, path, session, hint))
    if "antigravity" in selected:
        for root in (agy / "conversations", agy / "implicit"):
            if root.is_dir():
                try:
                    for path in root.iterdir():
                        if path.is_file() and path.suffix == ".db":
                            found.append(Source("antigravity", "sqlite-protobuf", path, path.stem))
                        elif path.is_file() and path.suffix == ".pb":
                            opaque.append(path)
                except OSError as e:
                    issues.append(f"antigravity: cannot enumerate {root}: {e}")
    if args.session:
        ids = [x.casefold() for x in args.session]
        found = [s for s in found if any(x in s.session.casefold() or x in s.path.name.casefold() for x in ids)]
        opaque = [p for p in opaque if any(x in p.stem.casefold() for x in ids)]
    if args.source == "text":
        found = [s for s in found if s.kind != "sqlite-protobuf"]
    elif args.source == "db":
        found = [s for s in found if s.kind == "sqlite-protobuf"]
    return found, issues, opaque


def source_metadata(source: Source, workspace_map: dict[str, set[str]]) -> tuple[str, str]:
    session, cwd = source.session, source.hint
    if source.path.name.endswith((".jsonl.gz", ".jsonl.zst")):
        return session, cwd
    if source.agent == "codex":
        for _, obj in read_json_lines(source.path, 3):
            if isinstance(obj, dict) and obj.get("type") == "session_meta" and isinstance(obj.get("payload"), dict):
                payload = obj["payload"]
                session = str(payload.get("id") or payload.get("session_id") or session)
                cwd = str(payload.get("cwd") or "")
                break
    elif source.agent == "claude":
        for _, obj in read_json_lines(source.path, 40):
            if isinstance(obj, dict) and isinstance(obj.get("cwd"), str):
                cwd = obj["cwd"]
                break
    elif source.agent == "antigravity":
        paths = sorted(workspace_map.get(session, set()))
        cwd = paths[0] if len(paths) == 1 else ""
    return session, cwd


def project_relation(cwd: str, project: Path | None) -> str:
    if not cwd or not project:
        return "unverified"
    try:
        actual = Path(cwd).expanduser().resolve()
        target = project.expanduser().resolve()
        return "candidate" if actual == target or target in actual.parents else "unverified"
    except (OSError, ValueError):
        return "unverified"


def json_part(value: dict) -> str:
    if "text" in value:
        return value["text"]
    return os.fsdecode(base64.b64decode(value.get("bytes", "")))


def strings(value, prefix: str = ""):
    if isinstance(value, str):
        # Images, opaque encrypted reasoning and other encoded binary are not transcript text.
        if len(value) > 512 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", value):
            return
        yield prefix, value
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from strings(item, f"{prefix}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ("encrypted_content", "signature"):
                continue
            yield from strings(item, f"{prefix}.{key}" if prefix else str(key))


def match_text(text: str, queries: list[str]) -> tuple[int, int] | None:
    folded = text.casefold()
    for query in queries:
        i = folded.find(query.casefold())
        if i >= 0:
            return i, len(query)
    return None


def snippet(text: str, match: tuple[int, int], size: int = 220) -> str:
    start = max(0, match[0] - size // 3)
    end = min(len(text), max(start + size, match[0] + match[1] + size // 4))
    return ("…" if start else "") + text[start:end].replace("\n", " ").replace("\r", " ") + ("…" if end < len(text) else "")


def record_details(obj) -> tuple[str, str]:
    if not isinstance(obj, dict):
        return "", "text"
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    role = payload.get("role") or message.get("role") or obj.get("source") or payload.get("type") or obj.get("type") or obj.get("method") or "record"
    timestamp = obj.get("timestamp") or obj.get("created_at") or payload.get("timestamp") or ""
    return str(timestamp), str(role)


def emit(source: Source, line: str, field: str, text: str, matched: tuple[int, int],
         metadata: dict[Path, tuple[str, str]], workspaces: dict[str, set[str]], project: Path | None,
         timestamp: str = "", role: str = "record") -> None:
    if source.path not in metadata:
        metadata[source.path] = source_metadata(source, workspaces)
    session, cwd = metadata[source.path]
    relation = project_relation(cwd, project)
    print(f"[{source.agent} | {source.kind} | session={session} | project={relation} | role/type={role} | time={timestamp or '?'}] "
          f"{source.path}:{line} | {field}: {snippet(text, matched)}", flush=True)


def patterns(queries: list[str]) -> list[str]:
    results: list[str] = []
    for q in queries:
        for p in (q, json.dumps(q, ensure_ascii=False)[1:-1], json.dumps(q, ensure_ascii=True)[1:-1]):
            if p not in results:
                results.append(p)
    return results


def search_text_group(group: list[Source], args: argparse.Namespace, metadata, workspaces) -> tuple[int, bool, list[str]]:
    count, capped = 0, False
    errors: list[str] = []
    by_path = {str(s.path): s for s in group}
    for begin in range(0, len(group), 64):
        batch = group[begin:begin + 64]
        cmd = ["rg", "--json", "--no-config", "--hidden", "--no-ignore", "--search-zip", "--ignore-case", "--fixed-strings"]
        for query in patterns(args.query):
            cmd += ["-e", query]
        cmd += ["--"] + [str(s.path) for s in batch]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        except OSError as e:
            errors.append(str(e))
            break
        assert proc.stdout is not None
        for raw in proc.stdout:
            try:
                event = json.loads(raw)
                if event.get("type") != "match":
                    continue
                data = event["data"]
                path = json_part(data["path"])
                record = json_part(data["lines"]).rstrip("\n")
                source = by_path.get(path)
                if source is None:
                    continue
                try:
                    obj = json.loads(record)
                except json.JSONDecodeError:
                    obj = record
                hit = next(((field, value, match_text(value, args.query)) for field, value in strings(obj)
                            if match_text(value, args.query)), None)
                if hit is None:
                    continue
                if count >= args.limit:
                    capped = True
                    proc.terminate()
                    break
                timestamp, role = record_details(obj)
                emit(source, str(data["line_number"]), hit[0] or "text", hit[1], hit[2], metadata,
                     workspaces, args.project, timestamp, role)
                count += 1
            except (KeyError, ValueError, TypeError) as e:
                errors.append(f"cannot parse search result: {e}")
        proc.stdout.close()
        stderr = proc.stderr.read().strip() if proc.stderr else ""
        returncode = proc.wait()
        if not capped and returncode not in (0, 1):
            errors.append(stderr or f"rg exited {returncode}")
        if capped:
            break
        if count >= args.limit and begin + 64 < len(group):
            capped = True
            break
    return count, capped, errors


def varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError("invalid varint")


def proto_fields(buf: bytes) -> list[tuple[int, bytes]]:
    pos, result = 0, []
    while pos < len(buf):
        key, pos = varint(buf, pos)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("invalid protobuf tag")
        if wire == 0:
            _, pos = varint(buf, pos)
        elif wire in (1, 5):
            pos += 8 if wire == 1 else 4
        elif wire == 2:
            length, pos = varint(buf, pos)
            if length > len(buf) - pos:
                raise ValueError("truncated protobuf field")
            result.append((number, buf[pos:pos + length]))
            pos += length
        else:
            raise ValueError("unsupported protobuf wire type")
        if pos > len(buf):
            raise ValueError("truncated protobuf value")
    return result


def proto_strings(buf: bytes, prefix: str = "", depth: int = 0):
    if depth > 16:
        return
    try:
        fields = proto_fields(buf)
    except ValueError:
        return
    for number, data in fields:
        field = f"{prefix}.{number}" if prefix else str(number)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if text and sum(ch.isprintable() or ch in "\n\r\t" for ch in text) / len(text) >= 0.95:
            yield field, text
        yield from proto_strings(data, field, depth + 1)


def search_db_group(group: list[Source], args: argparse.Namespace, metadata, workspaces) -> tuple[int, bool, list[str]]:
    count, capped, errors = 0, False, []
    byte_needles = {variation.encode("utf-8") for q in args.query for variation in (q, q.lower(), q.upper(), q.casefold())}
    for source in group:
        try:
            con = sqlite3.connect(source.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1.0)
            try:
                con.execute("PRAGMA query_only=ON")
                for idx, step_type, status, payload in con.execute("SELECT idx, step_type, status, step_payload FROM steps ORDER BY idx"):
                    if not isinstance(payload, bytes):
                        continue
                    folded_payload = payload.lower()
                    if not any(needle.lower() in folded_payload for needle in byte_needles):
                        continue
                    hit = next(((field, value, match_text(value, args.query)) for field, value in proto_strings(payload)
                                if match_text(value, args.query)), None)
                    if hit is None:
                        # A byte hit in an unknown schema is evidence of a possible match, not decoded conversation.
                        for needle in byte_needles:
                            pos = folded_payload.find(needle.lower())
                            if pos >= 0:
                                raw = payload[max(0, pos - 60):pos + len(needle) + 100].decode("utf-8", errors="replace")
                                hit = ("raw-bytes-unverified", raw, match_text(raw, args.query))
                                break
                    if hit is None or hit[2] is None:
                        continue
                    if count >= args.limit:
                        capped = True
                        break
                    emit(source, f"step={idx}", f"protobuf.{hit[0]}", hit[1], hit[2], metadata, workspaces,
                         args.project, role=f"step_type={step_type},status={status}")
                    count += 1
            finally:
                con.close()
        except (OSError, sqlite3.Error) as e:
            errors.append(f"{source.path}: {e}")
        if capped:
            break
    return count, capped, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", "-q", action="append", help="case-insensitive literal; repeat for OR")
    parser.add_argument("--agent", choices=AGENTS, action="append", help="restrict providers; repeatable")
    parser.add_argument("--project", type=Path, help="prioritize likely project sessions; not a strict filter")
    parser.add_argument("--session", action="append", help="restrict to session ID or filename substring; repeatable")
    parser.add_argument("--source", choices=("all", "text", "db"), default="all", help="restrict to text logs or Antigravity SQLite")
    parser.add_argument("--limit", type=int, default=8, help="maximum hits per provider and source type (default: 8)")
    parser.add_argument("--list-sources", action="store_true", help="show available source counts")
    parser.add_argument("--codex-home", help="override Codex home")
    parser.add_argument("--claude-home", help="override Claude config directory")
    parser.add_argument("--agy-home", help="override Antigravity CLI data directory")
    parser.add_argument("--grok-home", help="override Grok home")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if not args.list_sources and not args.query:
        parser.error("provide --query or --list-sources")
    if args.query and any(not q.strip() or "\n" in q or "\r" in q for q in args.query):
        parser.error("queries must be nonempty single-line literals")
    if not shutil.which("rg"):
        parser.error("ripgrep (rg) is required")
    records, problems, opaque = sources(args)
    agy = Path(args.agy_home or Path.home() / ".gemini/antigravity-cli").expanduser()
    workspaces = agy_workspaces(agy) if "antigravity" in set(args.agent or AGENTS) else {}
    metadata: dict[Path, tuple[str, str]] = {}
    if args.project:
        for source in records:
            metadata[source.path] = source_metadata(source, workspaces)
    def order(source: Source):
        relation = project_relation(metadata.get(source.path, ("", ""))[1], args.project)
        try:
            modified = source.path.stat().st_mtime
        except OSError:
            modified = 0
        return (0 if relation == "candidate" else 1, -modified, str(source.path))
    records.sort(key=order)
    groups: dict[tuple[str, str], list[Source]] = {}
    for source in records:
        groups.setdefault((source.agent, source.kind), []).append(source)
    providers = [agent for agent in AGENTS if agent in set(args.agent or AGENTS)]
    failed = bool(problems)
    for agent in providers:
        kinds = [(kind, group) for (provider, kind), group in groups.items() if provider == agent]
        if not kinds:
            print(f"[{agent}] no accessible sources for this selection")
        for kind, group in kinds:
            if args.list_sources:
                print(f"[{agent} | {kind}] {len(group)} file(s)")
                continue
            count, capped, errors = (search_db_group if kind == "sqlite-protobuf" else search_text_group)(group, args, metadata, workspaces)
            print(f"[{agent} | {kind}] {count} matching record(s), {len(group)} available file(s)" +
                  ("; capped: narrow query or raise --limit" if capped else ""), flush=True)
            problems.extend(errors)
            failed |= bool(errors)
    if "antigravity" in providers:
        projected = {s.session for s in records if s.agent == "antigravity" and s.kind in ("transcript", "transcript-chunk")}
        databases = {s.session for s in records if s.kind == "sqlite-protobuf"}
        missing = sum(p.stem not in projected and p.stem not in databases for p in opaque)
        print(f"[antigravity | coverage] {len(opaque)} opaque .pb file(s) not decoded; {missing} lack a selected text or SQLite projection; SQLite protobuf extraction is best-effort")
    for issue in problems:
        print(f"search warning: {issue}", file=sys.stderr)
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
