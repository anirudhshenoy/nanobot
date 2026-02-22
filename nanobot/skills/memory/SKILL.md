---
name: memory
description: Two-layer memory system with QMD-powered semantic search across memory and learning collections.
always: true
---

# Memory

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded in context. Search via QMD.
- `learning/` — Additional indexed notes and learnings.

## Search Memory (QMD)

Primary method — relevance-ranked search across all indexed collections:

```bash
qmd search "keyword"
```

Search specific collection:
```bash
qmd search "keyword" -c memory
qmd search "keyword" -c learning
```

Get specific file:
```bash
qmd get qmd://memory/memory.md
```

## Fallback: Exact Pattern Matching (grep)

For exact matches or regex patterns, use grep directly:

```bash
grep -i "exact phrase" memory/HISTORY.md
grep -iE "meeting|deadline" memory/HISTORY.md
```

## When to Use Which

| Use QMD | Use grep |
|---------|----------|
| Exploratory search | Exact phrase matching |
| Multiple keywords | Regex patterns |
| Relevance ranking | Specific file search |
| Cross-collection | Case-sensitive needs |

## When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.

## Indexing

Collections are pre-indexed with QMD. To re-index after adding new files:

```bash
qmd index memory memory/
qmd index learning learning/
```
