"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.utils.helpers import ensure_dir, get_sessions_path, timestamp


class SubagentManager:
    """
    Manages background subagent execution.
    
    Subagents are lightweight agent instances that run in the background
    to handle specific tasks. They share the same LLM provider but have
    isolated context and a focused system prompt.
    """
    
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        brave_api_key: str | None = None,
        tavily_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.brave_api_key = brave_api_key
        self.tavily_api_key = tavily_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._subagent_sessions_dir = ensure_dir(get_sessions_path() / "subagents")
    
    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> str:
        """
        Spawn a subagent to execute a task in the background.
        
        Args:
            task: The task description for the subagent.
            label: Optional human-readable label for the task.
            origin_channel: The channel to announce results to.
            origin_chat_id: The chat ID to announce results to.
        
        Returns:
            Status message indicating the subagent was started.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        
        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }
        self._log_subagent_event(
            task_id,
            {
                "event": "spawned",
                "label": display_label,
                "task": task,
                "origin": origin,
                "model": self.model,
            },
        )
        
        # Create background task
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        
        # Cleanup when done
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))
        
        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."
    
    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)
        self._log_subagent_event(task_id, {"event": "started", "label": label, "task": task})
        
        try:
            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            ))
            tools.register(WebSearchTool(brave_api_key=self.brave_api_key, tavily_api_key=self.tavily_api_key))
            tools.register(WebFetchTool())
            
            # Build messages with subagent-specific prompt
            system_prompt = self._build_subagent_prompt(task)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
            
            # Run agent loop (limited iterations)
            max_iterations = 15
            iteration = 0
            final_result: str | None = None
            token_usage: dict[str, int] = {"prompt": 0, "completion": 0, "total": 0, "cached": 0}
            total_cost: float = 0.0
            last_model_used = self.model
            last_provider_used: str | None = None
            
            while iteration < max_iterations:
                iteration += 1
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                if response.model:
                    last_model_used = response.model
                if response.provider:
                    last_provider_used = response.provider
                llm_usage: dict[str, Any] = {"event": "llm_usage", "iteration": iteration}
                if response.model:
                    llm_usage["model"] = response.model
                if response.provider:
                    llm_usage["provider"] = response.provider
                has_usage_data = False
                if response.usage:
                    prompt_tokens = response.usage.get("prompt_tokens", 0)
                    completion_tokens = response.usage.get("completion_tokens", 0)
                    total_tokens = response.usage.get("total_tokens", 0)
                    token_usage["prompt"] += prompt_tokens
                    token_usage["completion"] += completion_tokens
                    token_usage["total"] += total_tokens
                    llm_usage["prompt_tokens"] = prompt_tokens
                    llm_usage["completion_tokens"] = completion_tokens
                    llm_usage["total_tokens"] = total_tokens
                    has_usage_data = True

                    step_cost = response.usage.get("cost")
                    if step_cost is None:
                        step_cost = response.usage.get("total_cost")
                    if isinstance(step_cost, (int, float)):
                        total_cost += float(step_cost)
                        llm_usage["cost"] = float(step_cost)

                if response.cached_tokens:
                    token_usage["cached"] += response.cached_tokens
                    llm_usage["cached_tokens"] = response.cached_tokens
                    has_usage_data = True

                if has_usage_data:
                    self._log_subagent_event(task_id, llm_usage)
                
                if response.has_tool_calls:
                    self._log_subagent_event(
                        task_id,
                        {
                            "event": "assistant_tool_calls",
                            "iteration": iteration,
                            "content": response.content or "",
                            "tool_count": len(response.tool_calls),
                        },
                    )
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    
                    # Execute tools
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug("Subagent [{}] executing: {} with arguments: {}", task_id, tool_call.name, args_str)
                        self._log_subagent_event(
                            task_id,
                            {
                                "event": "tool_call",
                                "iteration": iteration,
                                "tool": tool_call.name,
                                "arguments": tool_call.arguments,
                            },
                        )
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        self._log_subagent_event(
                            task_id,
                            {
                                "event": "tool_result",
                                "iteration": iteration,
                                "tool": tool_call.name,
                                "result": result,
                            },
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content
                    self._log_subagent_event(
                        task_id,
                        {
                            "event": "final_response",
                            "iteration": iteration,
                            "content": final_result or "",
                        },
                    )
                    break
            
            if final_result is None:
                final_result = "Task completed but no final response was generated."
            
            logger.info("Subagent [{}] completed successfully", task_id)
            token_summary = self._build_token_summary(
                token_usage, total_cost, model=last_model_used, provider=last_provider_used,
            )
            self._log_subagent_event(
                task_id,
                {
                    "event": "completed",
                    "status": "ok",
                    "final_result": final_result,
                    **({"tokens": token_summary} if token_summary else {}),
                },
            )
            await self._announce_result(task_id, label, task, final_result, origin, "ok")
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            token_summary = (
                self._build_token_summary(
                    token_usage, total_cost,
                    model=last_model_used if "last_model_used" in locals() else None,
                    provider=last_provider_used if "last_provider_used" in locals() else None,
                )
                if "token_usage" in locals() else None
            )
            self._log_subagent_event(
                task_id,
                {
                    "event": "completed",
                    "status": "error",
                    "error": str(e),
                    "result": error_msg,
                    **({"tokens": token_summary} if token_summary else {}),
                },
            )
            await self._announce_result(task_id, label, task, error_msg, origin, "error")
    
    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"
        
        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). """
        
        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )
        
        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])
        self._log_subagent_event(
            task_id,
            {
                "event": "announced",
                "status": status,
                "target": f"{origin['channel']}:{origin['chat_id']}",
            },
        )
    
    def _build_subagent_prompt(self, task: str) -> str:
        """Build a focused system prompt for the subagent."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"

        return f"""# Subagent

## Current Time
{now} ({tz})

You are a subagent spawned by the main agent to complete a specific task.

## Rules
1. Stay focused - complete only the assigned task, nothing else
2. Your final response will be reported back to the main agent
3. Do not initiate conversations or take on side tasks
4. Be concise but informative in your findings

## What You Can Do
- Read and write files in the workspace
- Execute shell commands
- Search the web and fetch web pages
- Complete the task thoroughly

## What You Cannot Do
- Send messages directly to users (no message tool available)
- Spawn other subagents
- Access the main agent's conversation history

## Workspace
Your workspace is at: {self.workspace}
Skills are available at: {self.workspace}/skills/ (read SKILL.md files as needed)

When you have completed the task, provide a clear summary of your findings or actions."""
    
    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)

    def _get_subagent_log_path(self, task_id: str) -> Path:
        """Return the JSONL log path for a subagent run."""
        return self._subagent_sessions_dir / f"subagent_{task_id}.jsonl"

    def _log_subagent_event(self, task_id: str, payload: dict[str, Any]) -> None:
        """Append a subagent lifecycle/tool event to persistent JSONL logs."""
        entry = {"timestamp": timestamp(), "task_id": task_id, **payload}
        try:
            path = self._get_subagent_log_path(task_id)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Subagent [{task_id}] log write failed: {e}")

    def _build_token_summary(
        self,
        token_usage: dict[str, int],
        total_cost: float,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any] | None:
        """Build a compact token/cost summary for subagent logs."""
        if token_usage["total"] <= 0 and token_usage["cached"] <= 0 and total_cost <= 0:
            return None
        summary: dict[str, Any] = {
            "prompt": token_usage["prompt"],
            "completion": token_usage["completion"],
            "total": token_usage["total"],
        }
        if model:
            summary["model"] = model
        if provider:
            summary["provider"] = provider
        if token_usage["cached"] > 0:
            summary["cached_tokens"] = token_usage["cached"]
        if total_cost > 0:
            summary["cost"] = total_cost
        return summary
