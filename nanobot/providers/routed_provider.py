"""Rule-based model routing with configurable provider fallbacks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.config.schema import Config, ModelProviderConfig, RoutingRuleConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider


@dataclass(frozen=True)
class RouteTarget:
    """Concrete model+provider target."""

    model: str
    provider: str


@dataclass(frozen=True)
class RouteDecision:
    """Route result with an ordered attempt chain."""

    primary: RouteTarget
    chain: list[RouteTarget]
    reason: str


class QueryRouter:
    """Simple query classifier + rule matcher for model routing."""

    _TYPE_PATTERNS: dict[str, tuple[str, ...]] = {
        "coding": (
            "code",
            "bug",
            "debug",
            "refactor",
            "function",
            "class",
            "python",
            "javascript",
            "typescript",
            "sql",
            "stack trace",
        ),
        "reasoning": (
            "reason",
            "explain why",
            "step by step",
            "analyze",
            "compare",
            "tradeoff",
            "proof",
        ),
        "math": (
            "equation",
            "integral",
            "derivative",
            "theorem",
            "probability",
            "prove",
        ),
        "research": (
            "search",
            "latest",
            "news",
            "source",
            "citation",
            "references",
            "web",
        ),
        "creative": (
            "story",
            "poem",
            "brainstorm",
            "creative",
            "rewrite",
            "tone",
        ),
    }

    def __init__(
        self,
        default_target: RouteTarget,
        fallback_targets: list[RouteTarget],
        rules: list[RoutingRuleConfig],
    ):
        self.default_target = default_target
        self.fallback_targets = fallback_targets
        self.rules = rules

    def decide(self, query: str | None, preferred_target: RouteTarget | None = None) -> RouteDecision:
        """Pick primary target from rules, then append configured fallback chain."""
        effective_default = preferred_target or self.default_target
        text = (query or "").lower()
        inferred_types = self._infer_query_types(text)

        primary = effective_default
        reason = "default route"
        for rule in self.rules:
            if self._rule_matches(rule, text, inferred_types):
                primary = RouteTarget(model=rule.model, provider=rule.provider)
                label = rule.name or f"{rule.provider}:{rule.model}"
                reason = f"matched rule '{label}'"
                break

        chain = self._dedupe_targets([primary, *self.fallback_targets])
        return RouteDecision(primary=primary, chain=chain, reason=reason)

    def _infer_query_types(self, text: str) -> set[str]:
        inferred: set[str] = set()
        for query_type, patterns in self._TYPE_PATTERNS.items():
            if any(p in text for p in patterns):
                inferred.add(query_type)
        return inferred

    def _rule_matches(self, rule: RoutingRuleConfig, text: str, inferred_types: set[str]) -> bool:
        keyword_match = any(kw.lower() in text for kw in rule.keywords if kw)
        requested_types = {qt.lower() for qt in rule.query_types}
        type_match = bool(requested_types.intersection(inferred_types))
        if rule.keywords and rule.query_types:
            return keyword_match or type_match
        if rule.keywords:
            return keyword_match
        if rule.query_types:
            return type_match
        return False

    def _dedupe_targets(self, targets: list[RouteTarget]) -> list[RouteTarget]:
        seen: set[tuple[str, str]] = set()
        unique: list[RouteTarget] = []
        for target in targets:
            key = (target.provider, target.model)
            if key in seen:
                continue
            seen.add(key)
            unique.append(target)
        return unique


class RoutedLLMProvider(LLMProvider):
    """Provider wrapper that does query-based model routing and fallback retry."""

    def __init__(
        self,
        config: Config,
        default_model: str,
        default_provider_name: str | None,
        fallback_pairs: list[ModelProviderConfig],
        rules: list[RoutingRuleConfig],
        routing_enabled: bool = True,
    ):
        super().__init__(api_key=None, api_base=None)
        self.config = config
        self.provider_name = default_provider_name
        self.routing_enabled = routing_enabled
        self._default_target = RouteTarget(
            model=default_model,
            provider=default_provider_name or (config.get_provider_name(default_model) or ""),
        )
        fallback_targets = [
            RouteTarget(model=item.model, provider=item.provider) for item in fallback_pairs
        ]
        self.router = QueryRouter(
            default_target=self._default_target,
            fallback_targets=fallback_targets,
            rules=rules,
        )
        self._providers_cache: dict[tuple[str, str], LiteLLMProvider] = {}

    def get_default_model(self) -> str:
        return self._default_target.model

    def describe_routing(self, query: str | None = None) -> str:
        """Return a human-readable snapshot of routing config/decision."""
        preferred = self._default_target if not self.routing_enabled else None
        decision = self.router.decide(query, preferred_target=preferred)
        mode = "enabled" if self.routing_enabled else "disabled"
        fallbacks = decision.chain[1:]
        lines = [
            f"Model routing is {mode}.",
            f"Default target: {self._format_target(self._default_target)}",
            f"Selected target: {self._format_target(decision.primary)} ({decision.reason})",
            "Fallback chain:",
        ]
        if fallbacks:
            for i, target in enumerate(fallbacks, start=1):
                lines.append(f"  {i}. {self._format_target(target)}")
        else:
            lines.append("  (none)")

        if self.routing_enabled and self.router.rules:
            lines.append("Rules:")
            for i, rule in enumerate(self.router.rules, start=1):
                query_types = ", ".join(rule.query_types) if rule.query_types else "-"
                keywords = ", ".join(rule.keywords) if rule.keywords else "-"
                name = rule.name or f"{rule.provider}:{rule.model}"
                lines.append(
                    f"  {i}. {name} -> {rule.provider}:{rule.model} "
                    f"(queryTypes={query_types}; keywords={keywords})"
                )
        else:
            lines.append("Rules: none")
        return "\n".join(lines)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        query = self._extract_latest_user_message(messages)
        preferred = self._default_target if not self.routing_enabled else None
        if self.routing_enabled and model:
            preferred = RouteTarget(
                model=model,
                provider=self.config.get_provider_name(model) or self._default_target.provider,
            )
        decision = self.router.decide(query, preferred_target=preferred)
        logger.info(f"Model routing decision: {decision.reason}; chain={decision.chain}")

        last_error: LLMResponse | None = None
        for target in decision.chain:
            provider = self._get_provider(target)
            if not provider:
                logger.warning(f"Skipping route target without valid provider config: {target}")
                continue

            response = await provider.chat(
                messages=messages,
                tools=tools,
                model=target.model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            response.provider = provider.provider_name
            if not response.model:
                response.model = target.model
            if not self._is_provider_error(response):
                self.provider_name = provider.provider_name
                return response

            last_error = response
            logger.warning(
                f"LLM target failed ({target.provider}:{target.model}); "
                f"trying next fallback if available."
            )

        if last_error:
            return last_error
        return LLMResponse(
            content="Error calling LLM: no valid provider/model route found.",
            finish_reason="error",
            model=self._default_target.model,
            provider=self._default_target.provider,
        )

    def _get_provider(self, target: RouteTarget) -> LiteLLMProvider | None:
        provider_name = target.provider or self.config.get_provider_name(target.model) or self.config.get_provider_name()
        if not provider_name:
            return None

        key = (provider_name, target.model)
        if key in self._providers_cache:
            return self._providers_cache[key]

        provider_cfg = self.config.get_provider_by_name(provider_name)
        if not provider_cfg:
            return None
        if not provider_cfg.api_key and not target.model.startswith("bedrock/"):
            return None

        api_base = self.config.get_api_base_for_provider(provider_name, target.model)
        provider = LiteLLMProvider(
            api_key=provider_cfg.api_key or None,
            api_base=api_base,
            default_model=target.model,
            extra_headers=provider_cfg.extra_headers,
            provider_name=provider_name,
        )
        self._providers_cache[key] = provider
        return provider

    def _extract_latest_user_message(self, messages: list[dict[str, Any]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        text_parts.append(item["text"])
                if text_parts:
                    return " ".join(text_parts)
        return ""

    def _is_provider_error(self, response: LLMResponse) -> bool:
        if response.finish_reason == "error":
            return True
        content = response.content or ""
        return bool(re.match(r"^Error calling LLM:", content))

    def _format_target(self, target: RouteTarget) -> str:
        return f"{target.provider}:{target.model}"

