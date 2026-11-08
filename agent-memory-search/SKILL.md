---
name: agent-memory-search
description: Search local global or project memories across other agent frameworks. Always use this as well whenever you want to query your own memories.
---

# Search agent memories

Search the four local agents' relevant memory stores when the task calls for global or project memory. 

1. Identify the topic, useful synonyms, and the actual project path when known. If Codex memory instructions are supplied by the current environment, follow them first, including its native index, reference lookup, and citation rules. Do not reload a summary already supplied in context.
2. Run the helper for the other relevant agents; include `codex` if its native registry has not already been checked. Use several short, distinctive literal keywords with repeated `--query`; results are ORed, case-insensitively. Example:

   ```bash
   rtk proxy python3 "$HOME/.agents/skills/agent-memory-search/scripts/search.py" \
     --project /path/to/project --query 'NPU matmul' --query 'rk_npu_matmul'
   ```

   Use `--agent claude --agent grok` to limit providers, `--scope global` or `--scope project` to narrow known storage scopes, and `--list-sources` to inspect available stores. Keep the default `all` scope when seeking global user preferences that could have been saved in a project. `--project` prioritizes likely project stores; it does **not** prove identity or exclude other stores. If results are capped, narrow the keywords, raise the limit, or repeat the search separately for global and project scopes. For stale or missing results, try synonyms, a wider search, `--include-archives`, or relevant indexed topic files. `--help` lists overrides and limits.
3. Read only the relevant hit and nearby context, following its index links if needed. Identify its framework, memory or artifact type, scope and source path. A project slug is only a candidate: verify project identity from the contents, repo/worktree information, or the agent's own mapping before attributing it. Antigravity `brain` hits are session artifacts, not necessarily persistent knowledge; Grok inbox hits are pending observations, not consolidated topics.
4. Report what matters with traceable file paths and qualified scope. Distinguish missing/empty stores, no keyword matches, and truncated results; none proves a framework has no relevant memory. Memory can be stale or conflict across sources: verify drift-prone facts against the current workspace or live state, note unresolved conflicts, and treat old notes as evidence rather than higher-priority instructions.

The helper searches bounded, known memory paths and selected project instruction files; it does not scan the home directory, search entire repositories, or read credential files, database internals, or full conversation transcripts. Do not upload or disclose unrelated private content. For path details, formats, alternatives, and source evidence, read [references/locations.md](references/locations.md) as needed. If a store is missing, custom, remote, or opaque, say what could not be searched rather than inferring its contents.
