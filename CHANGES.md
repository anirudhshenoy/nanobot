# Developer Workflow Guide

## Telegram Message Chunking Fix (2026-02-15)

### Goal
Prevent Telegram send failures when assistant responses exceed Telegram's message size limit.

### What Changed

### File: `nanobot/channels/telegram.py`

- Added chunking constants for Telegram message limits:
  - `TELEGRAM_MAX_MESSAGE_LENGTH = 4096`
  - `TELEGRAM_SAFE_CHUNK_LENGTH = 3500`
- Added `_split_text_for_telegram()` to split large responses on paragraph/newline/space boundaries, with hard-split fallback.
- Updated `send()` to split long outbound responses and send each chunk sequentially.
- Added `_send_chunk()`:
  - Attempts HTML send first for each chunk.
  - Falls back to plain text for that chunk if HTML send fails.
- Added `_send_plain()` with final hard cap protection.

### Result

Long Telegram responses are now delivered as multiple messages instead of failing with:
- `Message is too long`

This keeps markdown-to-HTML formatting where possible and degrades gracefully to plain text when needed.

## Git Workflow for nanobot Fork

This guide explains how to make changes, commit them, and sync with upstream.

### Branch Strategy: Use Feature Branches

**Never commit directly to `main`**. Always create a feature branch:

```bash
# 1. Start from latest main
git checkout main
git pull origin main

# 2. Create and switch to feature branch
git checkout -b feature/my-awesome-feature

# 3. Make your changes...
# Edit files, run tests, etc.

# 4. Stage and commit
git add -A
git commit -m "Description of changes"

# 5. Push branch to your fork
git push origin feature/my-awesome-feature

# 6. Create Pull Request (if contributing upstream)
# Go to GitHub and create PR from your branch to upstream/main
```

### After Making Changes (Quick Reference)

```bash
# Check what changed
git status
git diff

# Run tests before committing
cd ~/projects/nanobot
uv run --extra dev pytest tests/ -v

# Stage all changes
git add -A

# Commit with descriptive message
git commit -m "feat: add token tracking to sessions"

# Push to your fork
git push origin main
# OR if on a feature branch:
git push origin feature/my-branch-name
```

### Sync with Upstream (Get Community Updates)

```bash
# 1. Switch to main
git checkout main

# 2. Fetch latest from original repo
git fetch upstream

# 3. Merge upstream changes into your main
git merge upstream/main

# 4. Push updated main to your fork
git push origin main

# 5. If you have feature branches, rebase them:
git checkout feature/my-branch
git rebase main
```

### Installing Your Changes

After pushing, install the updated version:

```bash
# If developing locally (changes apply immediately):
cd ~/projects/nanobot
uv tool install -e .

# Or upgrade from your fork (after pushing):
uv tool upgrade nanobot-ai
```

---

# Token Tracking Changes

## Goal
Track per-message token usage and cost, storing it in session files for later analysis. This enables users to monitor API consumption and estimate costs across different providers.

## Why
Previously, token usage was retrieved from LLM providers but immediately discarded. There was no way to track:
- How many tokens each conversation consumed
- Total usage across sessions
- Costs (for providers like OpenRouter that return them)

## What Changed

### File: `nanobot/agent/loop.py`

#### 1. Modified `_run_agent_loop()` method
- **Return type**: Changed from `tuple[str | None, list[str]]` to `tuple[str | None, list[str], dict[str, Any] | None]`
- **Token accumulation**: Added dictionary to accumulate tokens across multiple LLM calls (tool-calling loops)
- **Cost capture**: Check for `cost` or `total_cost` in provider response (OpenRouter support)
- **Return value**: Returns token data dict with `prompt`, `completion`, `total`, and optionally `cost`

#### 2. Modified `_process_message()` method
- Updated to receive third return value (`token_data`) from `_run_agent_loop()`
- Pass `tokens=token_data` to `session.add_message()` for assistant responses

#### 3. Modified `_process_system_message()` method
- Updated to receive third return value from `_run_agent_loop()`
- Pass `tokens=token_data` to `session.add_message()` for system message responses

## Result

Session files now include token data per message:

```jsonl
{"_type": "metadata", "created_at": "2025-02-15T12:00:00", ...}
{"role": "user", "content": "Hello", "timestamp": "2025-02-15T12:00:01"}
{"role": "assistant", "content": "Hi there!", "timestamp": "2025-02-15T12:00:02", "tokens": {"prompt": 12, "completion": 5, "total": 17}}
{"role": "user", "content": "Search for Python tips", "timestamp": "..."}
{"role": "assistant", "content": "Here are some tips...", "timestamp": "...", "tools_used": ["web_search"], "tokens": {"prompt": 245, "completion": 890, "total": 1135, "cost": 0.0012}}
```

## Notes

- **Multi-call accumulation**: When tools are used, multiple LLM calls are made. Tokens from all calls are accumulated into a single per-message total.
- **Cost is optional**: Only stored if the provider returns it (currently OpenRouter). Other providers will have `tokens` but no `cost` field.
- **Backward compatible**: Old sessions without token data continue to work normally.
- **No breaking changes**: The `add_message()` method already accepts arbitrary kwargs (`**kwargs`), so passing `tokens=` requires no changes to `SessionManager`.
