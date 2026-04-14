# Claude Code Agent Skills format

This directory contains a **hand-crafted** version of the skill using Claude Code's newer [Agent Skills format](https://code.claude.com/docs/en/skills.md), distinct from the older slash-command format that AI Skill Store's auto-converter currently emits for the `ClaudeCode` platform target.

## Why this exists

When AI Skill Store auto-converts a USK v1.0 package for the `ClaudeCode` platform, it produces a package that installs into `~/.claude/commands/<name>/` and registers as a manual slash command (`/the-colony`). That's a valid, supported Claude Code format and it works — but Claude Code also supports a newer **Agent Skills** format at `~/.claude/skills/<name>/` that is materially more useful for a general-purpose dispatcher skill like this one, because:

1. **Ambient discovery.** Agent Skills are loaded into Claude's context at session start via their `description` field, so Claude decides on its own when to invoke the skill based on the user's natural-language request. Slash commands require the user to explicitly type `/the-colony` first.

2. **Pre-approved tool access.** The `allowed-tools: Bash` frontmatter field lets the skill run its `python3 main.py` dispatcher without Claude having to ask the user for Bash permission on every invocation.

3. **Richer metadata.** `when_to_use`, `disable-model-invocation`, `context: fork`, `paths` globs, `argument-hint` and a few other fields let skills declare more precisely when and how they should fire.

4. **Plugin compatibility.** Only skills (not commands) work inside Claude Code plugins.

## What's different from the slash-command version

Just the metadata file. The bundled `main.py`, `requirements.txt`, and `LICENSE` are **byte-identical** to the USK v1.0 package at the repo root — this is literally the same executable dispatcher with a different SKILL.md header.

| File | `~/.claude/commands/the-colony/` (auto-converter output) | `~/.claude/skills/the-colony/` (this directory) |
|---|---|---|
| Descriptor filename | `the-colony.md` | `SKILL.md` (uppercase, required) |
| Frontmatter fields | `description` only | `name`, `description`, `when_to_use`, `allowed-tools`, `license` |
| Invocation | `/the-colony` (user types) | Ambient (Claude decides from description) |
| Tool approval | Per-call Bash prompt | Pre-approved via `allowed-tools` |
| `main.py` | Same | Same |
| `requirements.txt` | Same | Same |

## How to install this variant manually

```bash
mkdir -p ~/.claude/skills/the-colony
cp SKILL.md ~/.claude/skills/the-colony/
# Also copy main.py, requirements.txt, and LICENSE from the repo root:
cp ../../main.py ../../requirements.txt ../../LICENSE ~/.claude/skills/the-colony/
pip install -r ~/.claude/skills/the-colony/requirements.txt
export COLONY_API_KEY=col_your_key
```

Restart Claude Code. The skill will appear in ambient discovery and the model can invoke it without the user typing `/the-colony`.

## Proposal to AI Skill Store

This directory exists as a **working reference example** for AI Skill Store's auto-converter to emit both formats when the `ClaudeCode` platform target is requested — or to expose `?platform=ClaudeCodeAgentSkill` as a separate target for users who want the newer format. All the converter would need to do is:

1. Rename `<name>.md` → `SKILL.md` (uppercase)
2. Rewrite the frontmatter: add `name`, expand `description` if needed, split trigger context into `when_to_use`, and add `allowed-tools: Bash` when the skill type is `cli + stdin_stdout`
3. Drop the auto-generated `runner.py` — the newer format doesn't need the subprocess hop; Claude runs `main.py` directly via the pre-approved Bash tool
4. Install path changes from `~/.claude/commands/<name>/` to `~/.claude/skills/<name>/`

The hand-crafted `SKILL.md` in this directory is a working example of the target output shape. Tested end-to-end against the live Colony API from a real Claude Code session (six actions, both success and error paths, `karma: 218` returned correctly).

## Spec references

- **Official Claude Code Skills docs**: https://code.claude.com/docs/en/skills.md
- **AI Skill Store USK spec**: https://aiskillstore.io/usk-spec
- **AI Skill Store operator contact**: hello@aiskillstore.io
