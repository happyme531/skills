# Memory locations and boundaries

Paths are defaults for local Linux installations. The helper accepts home-directory overrides. Layouts can change; inspect the installed version's documentation and configuration when needed. Sources below were checked on 2026-11-09.

## Codex

- `$CODEX_HOME/memories/MEMORY.md`, or `~/.codex/memories/MEMORY.md`, is the native searchable registry in this environment. Its entries may point to topic files and rollout summaries. Follow the current environment's native memory instructions for which files to open and how to cite them. Some environments supply `memory_summary.md` in context already; don't reread it if prohibited.
- The helper searches only the registry, which mixes global and project entries. It does not search all raw sessions or rollout summaries. If relevant entries point to those, open only the indicated files. Memory may not exist in every Codex installation or may be elsewhere.

## Claude Code

- `$CLAUDE_CONFIG_DIR/projects/<encoded-project>/memory/`, default `~/.claude/projects/...`, holds project auto-memory index and topics. The repository identity can be shared by subdirectories/worktrees; the exact encoded folder or custom directory may differ from a path-derived guess.
- `$CLAUDE_CONFIG_DIR/CLAUDE.md` and project `CLAUDE.md`/`CLAUDE.local.md` are persistent user instructions, not auto-memory. They are labeled separately. User and selected-project `.claude/rules/` and agent-memory directories are also separate types.
- `autoMemoryDirectory` can be set in user, project, local, managed, or session settings, and `CLAUDE_CODE_PROJECT_DIR_NAME` can alter the normal mapping. The helper considers user and selected-project settings and the current environment; a past session's settings or managed scope may differ. [Official documentation](https://code.claude.com/docs/en/memory).

## Antigravity CLI

- `~/.gemini/antigravity-cli/knowledge/` is the CLI's locally observed knowledge directory. Markdown and `metadata.json` there are searched as knowledge candidates; an empty directory does not establish that the agent has no remote or opaque memory.
- `~/.gemini/antigravity-cli/brain/<conversation-id>/` holds conversation artifacts. Search current Markdown artifacts as supplementary, unverified-scope evidence, labeled `artifact`; don't treat them as persistent memories. The helper excludes `.system_generated` transcripts and versioned files by default.
- Desktop/IDE data under `~/.gemini/antigravity/` is separate from the CLI and is included only with `--include-antigravity-desktop`. The local directory layout is an observation, not a guaranteed public storage API. See [Google's Antigravity documentation](https://antigravity.google/docs) and [CLI changelog](https://antigravity.google/docs/changelog?tab=cli).

## Grok Build

- Current v2 memory lives in `~/.grok/memory-v2/global/` and `~/.grok/memory-v2/workspaces/<slug>-<hash>/`. `MEMORY.md` is a generated index; `topics/` contains consolidated notes; `observations/_inbox/` contains pending observations. `archive/` is older processed material and is searched only with `--include-archives`.
- Legacy `~/.grok/memory/MEMORY.md` and workspace directories may also exist. The helper labels these legacy; migration can leave old files behind, so prefer verified current v2 notes.
- Grok derives the workspace suffix from repository identity or a canonical path. A slug match alone cannot prove identity, particularly for same-named repositories or renamed remotes. Verify before attributing a result. See [xAI's memory overview](https://x.ai/news/grok-build-memory), [storage implementation](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-memory/src/storage.rs), and the installed `~/.grok/docs/user-guide/13-memory.md` where present.
