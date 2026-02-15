# Developer Workflow Guide

## Web Search Fallback Chain (2026-02-15)

### Goal
Add resilient web search with automatic fallback when any search engine fails.

### Why
Previously, `web_search` relied solely on Brave Search API. If the API key was missing, rate-limited, or returned any error, the tool would fail with no alternatives.

### What Changed

#### File: `nanobot/agent/tools/web.py`

- **Added dependency**: `duckduckgo-search>=8.0.0` for free, no-API-key search
- **Refactored `WebSearchTool`** to support fallback chain:
  - `_search_brave()` — Brave Search API (requires `BRAVE_API_KEY`)
  - `_search_tavily()` — Tavily API (requires `TAVILY_API_KEY`)
  - `_search_duckduckgo()` — DuckDuckGo (no API key, always available)
- **Fallback logic**: Try each engine in order; on *any* error, fall back to next
- **Result attribution**: Output now shows which engine was used: `Results for: query [Brave]`

#### File: `pyproject.toml`

- Added `duckduckgo-search>=8.0.0` to dependencies

### Result

```python
# With BRAVE_API_KEY set:
Results for: Python async tutorial [Brave]

# If Brave fails (rate limit, timeout, etc.):
Results for: Python async tutorial [Tavily]

# If both Brave and Tavily fail or lack keys:
Results for: Python async tutorial [DuckDuckGo]
```

### Notes

- **No breaking changes**: Existing `BRAVE_API_KEY` configuration continues to work
- **New env var support**: `TAVILY_API_KEY` enables Tavily as first fallback
- **Always works**: DuckDuckGo requires no API key, ensuring search never completely fails
- **Graceful degradation**: Each engine failure logs the error and tries the next

---

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

---

# Kilo Provider Changes

## Goal
Add first-class support for Kilo AI as an OpenAI-compatible gateway provider so users can configure it directly (without relying on `custom`).

## Why
Kilo AI exposes a chat completions endpoint at:
- `https://api.kilo.ai/api/gateway/chat/completions`

The model naming can include path-like segments (for example `z-ai/glm-5:free`), so provider routing must preserve those model names.

## What Changed

### File: `nanobot/providers/registry.py`

#### 1. Added new provider spec: `kilo`
- **Provider type**: gateway (`is_gateway=True`)
- **Display name**: `Kilo AI`
- **Auth env key**: `OPENAI_API_KEY` (OpenAI-compatible)
- **LiteLLM prefix**: `openai`
- **Auto-detect by base**: `detect_by_base_keyword="kilo.ai"`
- **Default API base**: `https://api.kilo.ai/api/gateway`
- **Model handling**: `strip_model_prefix=False` to preserve models like `z-ai/glm-5:free`

#### 2. Added matching keywords
- `keywords=("kilo", "z-ai")` to help model-based provider matching when `kilo` is configured.

### File: `nanobot/config/schema.py`

#### 1. Extended `ProvidersConfig`
- Added `kilo: ProviderConfig = Field(default_factory=ProviderConfig)`.
- Enables config via `providers.kilo` in `~/.nanobot/config.json`.

## Result

Users can now configure Kilo directly:

```json
{
  "providers": {
    "kilo": {
      "api_key": "KILO_API_KEY",
      "api_base": "https://api.kilo.ai/api/gateway"
    }
  },
  "agents": {
    "defaults": {
      "model": "z-ai/glm-5:free"
    }
  }
}
```

And `api_base` can be omitted because Kilo has a registry default.

## Notes

- `kilo` is registered before `zhipu`, so model names containing `z-ai` will resolve to Kilo first when both are configured.
- Gateway detection still prioritizes explicit `provider_name`, ensuring stable routing when `providers.kilo` is selected.
