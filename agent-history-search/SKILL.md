---
name: agent-history-search
description: Search full local conversation transcripts across Codex, Claude Code, Antigravity CLI and Grok Build. Use only when the user explicitly asks to search, inspect, find, or recover historical conversations, chat records, session transcripts, or dialogue logs; do not trigger for ordinary memory lookup or implied project context.
---

# Search agent conversation history

Search history only when explicitly requested; an ordinary request to recall a preference or project decision is not a request to search transcripts. Search the four providers by default, or honor the user's specified provider, project, session, and other constraints. History may contain private prompts and tool outputs: search locally, return only relevant excerpts, and never upload logs.

Use distinctive terms or quoted phrases and practical aliases. The read-only helper searches the content of user and assistant messages, reasoning and tool records, not just titles or first prompts:

```bash
rtk proxy python3 "$HOME/.agents/skills/agent-history-search/scripts/search.py" \
  --project /path/to/project --query '关键词' --query 'alternative'
```

Repeated `--query` terms are ORed and treated as case-insensitive literals. Use repeated `--agent` to restrict providers, `--session` to restrict an ID or filename substring, `--source text` or `--source db` to isolate text or Antigravity SQLite, and `--list-sources` to inspect coverage. `--project` prioritizes likely matches; it is not a strict project filter and does not prove identity. `--limit` caps hits per provider and source type; if capped, narrow the query or raise the limit before concluding the search. Use `--help` for data-root overrides.

Inspect relevant hits in context before answering: identify provider, session, timestamp, project if verifiable, role/type, and exact file plus line or SQLite step. To reconstruct a conversation, read the needed neighboring records in order and distinguish direct quotes from a summary. Multiple projections and tool logs can duplicate the same message; a search may also match a later transcript quoting an older one, or this very search. Verify the original occurrence rather than attributing every hit to the same event.

Do not claim exhaustive history from a zero-hit search. Missing, archived, rotated, remote, encrypted, compacted or partially decoded records can be unavailable. Antigravity SQLite/protobuf results are best-effort field extraction, while `.pb` files without a readable projection remain opaque; the helper reports their coverage. The storage layouts, limitations and further retrieval guidance are in [references/formats.md](references/formats.md).
