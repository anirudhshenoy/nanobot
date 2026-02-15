"""Rule-based model routing with weighted scoring and configurable provider fallbacks."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from loguru import logger

from nanobot.config.schema import (
    Config,
    ModelProviderConfig,
    RoutingScoringConfig,
    RoutingTierTargetConfig,
    RoutingTiersConfig,
)
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider

Tier = Literal["SIMPLE", "MEDIUM", "COMPLEX", "REASONING"]


@dataclass(frozen=True)
class RouteTarget:
    """Concrete model+provider target."""

    model: str
    provider: str


@dataclass(frozen=True)
class DimensionScore:
    """One weighted scoring dimension result."""

    name: str
    score: float
    signal: str | None


@dataclass(frozen=True)
class ScoringResult:
    """Weighted classifier output."""

    score: float
    tier: Tier | None
    confidence: float
    signals: list[str]
    agentic_score: float = 0.0


@dataclass(frozen=True)
class RouteDecision:
    """Route result with an ordered attempt chain."""

    primary: RouteTarget
    chain: list[RouteTarget]
    reason: str
    tier: Tier | None = None
    score: float = 0.0
    confidence: float = 0.0
    signals: list[str] | None = None
    agentic_score: float = 0.0


def score_token_count(estimated_tokens: int, thresholds: dict[str, int]) -> DimensionScore:
    if estimated_tokens < thresholds["simple"]:
        return DimensionScore("tokenCount", -1.0, f"short ({estimated_tokens} tokens)")
    if estimated_tokens > thresholds["complex"]:
        return DimensionScore("tokenCount", 1.0, f"long ({estimated_tokens} tokens)")
    return DimensionScore("tokenCount", 0.0, None)


def score_keyword_match(
    text: str,
    keywords: list[str],
    name: str,
    signal_label: str,
    thresholds: dict[str, int],
    scores: dict[str, float],
) -> DimensionScore:
    matches = [kw for kw in keywords if kw.lower() in text]
    if len(matches) >= thresholds["high"]:
        return DimensionScore(name, scores["high"], f"{signal_label} ({', '.join(matches[:3])})")
    if len(matches) >= thresholds["low"]:
        return DimensionScore(name, scores["low"], f"{signal_label} ({', '.join(matches[:3])})")
    return DimensionScore(name, scores["none"], None)


def score_multi_step(text: str) -> DimensionScore:
    patterns = [r"first.*then", r"step \d", r"\d\.\s"]
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
        return DimensionScore("multiStepPatterns", 0.5, "multi-step")
    return DimensionScore("multiStepPatterns", 0.0, None)


def score_question_complexity(prompt: str) -> DimensionScore:
    count = prompt.count("?")
    if count > 3:
        return DimensionScore("questionComplexity", 0.5, f"{count} questions")
    return DimensionScore("questionComplexity", 0.0, None)


def score_agentic_task(text: str, keywords: list[str]) -> tuple[DimensionScore, float]:
    match_count = 0
    signals: list[str] = []
    for keyword in keywords:
        if keyword.lower() in text:
            match_count += 1
            if len(signals) < 3:
                signals.append(keyword)

    if match_count >= 4:
        return DimensionScore("agenticTask", 1.0, f"agentic ({', '.join(signals)})"), 1.0
    if match_count >= 3:
        return DimensionScore("agenticTask", 0.6, f"agentic ({', '.join(signals)})"), 0.6
    if match_count >= 1:
        return DimensionScore("agenticTask", 0.2, f"agentic-light ({', '.join(signals)})"), 0.2
    return DimensionScore("agenticTask", 0.0, None), 0.0


def calibrate_confidence(distance: float, steepness: float) -> float:
    return 1 / (1 + math.exp(-steepness * distance))


class QueryRouter:
    """Weighted scoring classifier + tier mapper."""

    def __init__(
        self,
        default_target: RouteTarget,
        global_fallback_targets: list[RouteTarget],
        scoring_config: RoutingScoringConfig,
        tier_targets: RoutingTiersConfig,
    ):
        self.default_target = default_target
        self.global_fallback_targets = global_fallback_targets
        self.scoring_config = scoring_config
        self.tier_targets = tier_targets

    def classify_by_rules(
        self,
        prompt: str,
        system_prompt: str | None,
        estimated_tokens: int,
    ) -> ScoringResult:
        config = self.scoring_config
        text = f"{system_prompt or ''} {prompt}".lower()
        user_text = prompt.lower()

        dimensions: list[DimensionScore] = [
            score_token_count(
                estimated_tokens,
                {
                    "simple": config.token_count_thresholds.simple,
                    "complex": config.token_count_thresholds.complex,
                },
            ),
            score_keyword_match(
                text,
                config.code_keywords,
                "codePresence",
                "code",
                {"low": 1, "high": 2},
                {"none": 0.0, "low": 0.5, "high": 1.0},
            ),
            score_keyword_match(
                user_text,
                config.reasoning_keywords,
                "reasoningMarkers",
                "reasoning",
                {"low": 1, "high": 2},
                {"none": 0.0, "low": 0.7, "high": 1.0},
            ),
            score_keyword_match(
                text,
                config.technical_keywords,
                "technicalTerms",
                "technical",
                {"low": 2, "high": 4},
                {"none": 0.0, "low": 0.5, "high": 1.0},
            ),
            score_keyword_match(
                text,
                config.creative_keywords,
                "creativeMarkers",
                "creative",
                {"low": 1, "high": 2},
                {"none": 0.0, "low": 0.5, "high": 0.7},
            ),
            score_keyword_match(
                text,
                config.simple_keywords,
                "simpleIndicators",
                "simple",
                {"low": 1, "high": 2},
                {"none": 0.0, "low": -1.0, "high": -1.0},
            ),
            score_multi_step(text),
            score_question_complexity(prompt),
            score_keyword_match(
                text,
                config.imperative_verbs,
                "imperativeVerbs",
                "imperative",
                {"low": 1, "high": 2},
                {"none": 0.0, "low": 0.3, "high": 0.5},
            ),
            score_keyword_match(
                text,
                config.constraint_indicators,
                "constraintCount",
                "constraints",
                {"low": 1, "high": 3},
                {"none": 0.0, "low": 0.3, "high": 0.7},
            ),
            score_keyword_match(
                text,
                config.output_format_keywords,
                "outputFormat",
                "format",
                {"low": 1, "high": 2},
                {"none": 0.0, "low": 0.4, "high": 0.7},
            ),
            score_keyword_match(
                text,
                config.reference_keywords,
                "referenceComplexity",
                "references",
                {"low": 1, "high": 2},
                {"none": 0.0, "low": 0.3, "high": 0.5},
            ),
            score_keyword_match(
                text,
                config.negation_keywords,
                "negationComplexity",
                "negation",
                {"low": 2, "high": 3},
                {"none": 0.0, "low": 0.3, "high": 0.5},
            ),
            score_keyword_match(
                text,
                config.domain_specific_keywords,
                "domainSpecificity",
                "domain-specific",
                {"low": 1, "high": 2},
                {"none": 0.0, "low": 0.5, "high": 0.8},
            ),
        ]

        agentic_dimension, agentic_score = score_agentic_task(text, config.agentic_task_keywords)
        dimensions.append(agentic_dimension)

        signals = [d.signal for d in dimensions if d.signal is not None]

        weighted_score = 0.0
        for dim in dimensions:
            weighted_score += dim.score * config.dimension_weights.get(dim.name, 0.0)

        reasoning_matches = [kw for kw in config.reasoning_keywords if kw.lower() in user_text]
        if len(reasoning_matches) >= 2:
            confidence = calibrate_confidence(
                max(weighted_score, 0.3),
                config.confidence_steepness,
            )
            return ScoringResult(
                score=weighted_score,
                tier="REASONING",
                confidence=max(confidence, 0.85),
                signals=signals,
                agentic_score=agentic_score,
            )

        boundaries = config.tier_boundaries
        distance_from_boundary = 0.0
        tier: Tier
        if weighted_score < boundaries.simple_medium:
            tier = "SIMPLE"
            distance_from_boundary = boundaries.simple_medium - weighted_score
        elif weighted_score < boundaries.medium_complex:
            tier = "MEDIUM"
            distance_from_boundary = min(
                weighted_score - boundaries.simple_medium,
                boundaries.medium_complex - weighted_score,
            )
        elif weighted_score < boundaries.complex_reasoning:
            tier = "COMPLEX"
            distance_from_boundary = min(
                weighted_score - boundaries.medium_complex,
                boundaries.complex_reasoning - weighted_score,
            )
        else:
            tier = "REASONING"
            distance_from_boundary = weighted_score - boundaries.complex_reasoning

        confidence = calibrate_confidence(distance_from_boundary, config.confidence_steepness)
        if confidence < config.confidence_threshold:
            return ScoringResult(
                score=weighted_score,
                tier=None,
                confidence=confidence,
                signals=signals,
                agentic_score=agentic_score,
            )

        return ScoringResult(
            score=weighted_score,
            tier=tier,
            confidence=confidence,
            signals=signals,
            agentic_score=agentic_score,
        )

    def decide(
        self,
        query: str | None,
        system_prompt: str | None,
        estimated_tokens: int,
        preferred_target: RouteTarget | None = None,
        force_default: bool = False,
    ) -> RouteDecision:
        effective_default = preferred_target or self.default_target
        if force_default:
            chain = self._dedupe_targets([effective_default, *self.global_fallback_targets])
            return RouteDecision(primary=effective_default, chain=chain, reason="routing disabled")

        scoring = self.classify_by_rules(query or "", system_prompt, estimated_tokens)
        primary = effective_default
        tier_fallback: list[RouteTarget] = []
        reason = "default route"

        if scoring.tier is not None:
            tier_target = self._get_tier_target(scoring.tier)
            if tier_target:
                primary = RouteTarget(
                    model=tier_target.primary.model,
                    provider=tier_target.primary.provider,
                )
                tier_fallback = [
                    RouteTarget(model=item.model, provider=item.provider) for item in tier_target.fallback
                ]
                reason = (
                    f"weighted scoring -> {scoring.tier} "
                    f"(score={scoring.score:.3f}, confidence={scoring.confidence:.2f})"
                )
            else:
                reason = (
                    f"weighted scoring -> {scoring.tier}, but tier target missing; using default "
                    f"(score={scoring.score:.3f}, confidence={scoring.confidence:.2f})"
                )
        else:
            # Low confidence - use default
            reason = (
                f"weighted scoring ambiguous, using default "
                f"(score={scoring.score:.3f}, confidence={scoring.confidence:.2f})"
            )

        chain = self._dedupe_targets([primary, *tier_fallback, *self.global_fallback_targets])
        return RouteDecision(
            primary=primary,
            chain=chain,
            reason=reason,
            tier=scoring.tier,
            score=scoring.score,
            confidence=scoring.confidence,
            signals=scoring.signals,
            agentic_score=scoring.agentic_score,
        )

    def _get_tier_target(self, tier: Tier) -> RoutingTierTargetConfig | None:
        if tier == "SIMPLE":
            return self.tier_targets.simple
        if tier == "MEDIUM":
            return self.tier_targets.medium
        if tier == "COMPLEX":
            return self.tier_targets.complex
        return self.tier_targets.reasoning

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
    """Provider wrapper that does weighted query routing and fallback retry."""

    def __init__(
        self,
        config: Config,
        default_model: str,
        default_provider_name: str | None,
        fallback_pairs: list[ModelProviderConfig],
        scoring_config: RoutingScoringConfig,
        tier_targets: RoutingTiersConfig,
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
        fallback_targets = [RouteTarget(model=item.model, provider=item.provider) for item in fallback_pairs]
        self.router = QueryRouter(
            default_target=self._default_target,
            global_fallback_targets=fallback_targets,
            scoring_config=scoring_config,
            tier_targets=tier_targets,
        )
        self._providers_cache: dict[tuple[str, str], LiteLLMProvider] = {}

    def get_default_model(self) -> str:
        return self._default_target.model

    def describe_routing(self, query: str | None = None) -> str:
        """Return a human-readable snapshot of routing config/decision."""
        estimated_tokens = self._estimate_tokens(query or "")
        decision = self.router.decide(
            query=query,
            system_prompt=None,
            estimated_tokens=estimated_tokens,
            force_default=not self.routing_enabled,
        )
        mode = "enabled" if self.routing_enabled else "disabled"
        fallbacks = decision.chain[1:]
        lines = [
            f"Model routing is {mode}.",
            f"Default target: {self._format_target(self._default_target)}",
            f"Selected target: {self._format_target(decision.primary)} ({decision.reason})",
        ]
        if decision.tier:
            lines.append(
                f"Tier: {decision.tier} | score={decision.score:.3f} | confidence={decision.confidence:.2f} "
                f"| agenticScore={decision.agentic_score:.2f}"
            )
        lines.append("Fallback chain:")
        if fallbacks:
            for i, target in enumerate(fallbacks, start=1):
                lines.append(f"  {i}. {self._format_target(target)}")
        else:
            lines.append("  (none)")
        if decision.signals:
            lines.append(f"Signals: {', '.join(decision.signals[:6])}")
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
        system_prompt = self._extract_system_prompt(messages)
        preferred = None
        if model:
            preferred = RouteTarget(
                model=model,
                provider=self.config.get_provider_name(model) or self._default_target.provider,
            )

        decision = self.router.decide(
            query=query,
            system_prompt=system_prompt,
            estimated_tokens=self._estimate_tokens(f"{system_prompt or ''} {query}"),
            preferred_target=preferred,
            force_default=not self.routing_enabled,
        )
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
        provider_name = (
            target.provider
            or self.config.get_provider_name(target.model)
            or self.config.get_provider_name()
        )
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

    def _extract_system_prompt(self, messages: list[dict[str, Any]]) -> str | None:
        for msg in messages:
            if msg.get("role") == "system" and isinstance(msg.get("content"), str):
                return msg["content"]
        return None

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _is_provider_error(self, response: LLMResponse) -> bool:
        if response.finish_reason == "error":
            return True
        content = response.content or ""
        return bool(re.match(r"^Error calling LLM:", content))

    def _format_target(self, target: RouteTarget) -> str:
        return f"{target.provider}:{target.model}"
