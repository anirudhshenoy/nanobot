"""Configuration schema using Pydantic."""

from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WhatsAppConfig(Base):
    """WhatsApp channel configuration."""

    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    bridge_token: str = ""  # Shared token for bridge auth (optional, recommended)
    allow_from: list[str] = Field(default_factory=list)  # Allowed phone numbers


class TelegramConfig(Base):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames
    proxy: str | None = None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    reply_to_message: bool = False  # If true, bot replies quote the original message


class FeishuConfig(Base):
    """Feishu/Lark channel configuration using WebSocket long connection."""

    enabled: bool = False
    app_id: str = ""  # App ID from Feishu Open Platform
    app_secret: str = ""  # App Secret from Feishu Open Platform
    encrypt_key: str = ""  # Encrypt Key for event subscription (optional)
    verification_token: str = ""  # Verification Token for event subscription (optional)
    allow_from: list[str] = Field(default_factory=list)  # Allowed user open_ids


class DingTalkConfig(Base):
    """DingTalk channel configuration using Stream mode."""

    enabled: bool = False
    client_id: str = ""  # AppKey
    client_secret: str = ""  # AppSecret
    allow_from: list[str] = Field(default_factory=list)  # Allowed staff_ids


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from Discord Developer Portal
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377  # GUILDS + GUILD_MESSAGES + DIRECT_MESSAGES + MESSAGE_CONTENT


class EmailConfig(Base):
    """Email channel configuration (IMAP inbound + SMTP outbound)."""

    enabled: bool = False
    consent_granted: bool = False  # Explicit owner permission to access mailbox data

    # IMAP (receive)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_use_ssl: bool = True

    # SMTP (send)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_address: str = ""

    # Behavior
    auto_reply_enabled: bool = True  # If false, inbound email is read but no automatic reply is sent
    poll_interval_seconds: int = 30
    mark_seen: bool = True
    max_body_chars: int = 12000
    subject_prefix: str = "Re: "
    allow_from: list[str] = Field(default_factory=list)  # Allowed sender email addresses


class MochatMentionConfig(Base):
    """Mochat mention behavior configuration."""

    require_in_groups: bool = False


class MochatGroupRule(Base):
    """Mochat per-group mention requirement."""

    require_mention: bool = False


class MochatConfig(Base):
    """Mochat channel configuration."""

    enabled: bool = False
    base_url: str = "https://mochat.io"
    socket_url: str = ""
    socket_path: str = "/socket.io"
    socket_disable_msgpack: bool = False
    socket_reconnect_delay_ms: int = 1000
    socket_max_reconnect_delay_ms: int = 10000
    socket_connect_timeout_ms: int = 10000
    refresh_interval_ms: int = 30000
    watch_timeout_ms: int = 25000
    watch_limit: int = 100
    retry_delay_ms: int = 500
    max_retry_attempts: int = 0  # 0 means unlimited retries
    claw_token: str = ""
    agent_user_id: str = ""
    sessions: list[str] = Field(default_factory=list)
    panels: list[str] = Field(default_factory=list)
    allow_from: list[str] = Field(default_factory=list)
    mention: MochatMentionConfig = Field(default_factory=MochatMentionConfig)
    groups: dict[str, MochatGroupRule] = Field(default_factory=dict)
    reply_delay_mode: str = "non-mention"  # off | non-mention
    reply_delay_ms: int = 120000


class SlackDMConfig(Base):
    """Slack DM policy configuration."""

    enabled: bool = True
    policy: str = "open"  # "open" or "allowlist"
    allow_from: list[str] = Field(default_factory=list)  # Allowed Slack user IDs


class SlackConfig(Base):
    """Slack channel configuration."""

    enabled: bool = False
    mode: str = "socket"  # "socket" supported
    webhook_path: str = "/slack/events"
    bot_token: str = ""  # xoxb-...
    app_token: str = ""  # xapp-...
    user_token_read_only: bool = True
    reply_in_thread: bool = True
    react_emoji: str = "eyes"
    group_policy: str = "mention"  # "mention", "open", "allowlist"
    group_allow_from: list[str] = Field(default_factory=list)  # Allowed channel IDs if allowlist
    dm: SlackDMConfig = Field(default_factory=SlackDMConfig)


class QQConfig(Base):
    """QQ channel configuration using botpy SDK."""

    enabled: bool = False
    app_id: str = ""  # 机器人 ID (AppID) from q.qq.com
    secret: str = ""  # 机器人密钥 (AppSecret) from q.qq.com
    allow_from: list[str] = Field(default_factory=list)  # Allowed user openids (empty = public access)


class ChannelsConfig(Base):
    """Configuration for chat channels."""

    send_progress: bool = True    # stream agent's text progress to the channel
    send_tool_hints: bool = False  # stream tool-call hints (e.g. read_file("…"))
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    mochat: MochatConfig = Field(default_factory=MochatConfig)
    dingtalk: DingTalkConfig = Field(default_factory=DingTalkConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    qq: QQConfig = Field(default_factory=QQConfig)


class AgentDefaults(Base):
    """Default agent configuration."""

    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    provider: str | None = None  # Optional explicit provider override for defaults.model
    max_tokens: int = 8192
    temperature: float = 0.1
    max_tool_iterations: int = 40
    memory_window: int = 100
    memory_consolidation: bool = False


class ModelProviderConfig(Base):
    """A model+provider pair used for routing and fallback."""
    model: str
    provider: str


class TokenCountThresholdsConfig(Base):
    """Token threshold config for weighted scoring."""
    simple: int = 400
    complex: int = 2500


class TierBoundariesConfig(Base):
    """Weighted score boundaries between tiers."""
    simple_medium: float = -0.1
    medium_complex: float = 0.15
    complex_reasoning: float = 0.4


class RoutingScoringConfig(Base):
    """Weighted scoring parameters (ported from the v2 classifier)."""
    token_count_thresholds: TokenCountThresholdsConfig = Field(default_factory=TokenCountThresholdsConfig)

    code_keywords: list[str] = Field(
        default_factory=lambda: [
            "code", "function", "class", "api", "debug", "bug", "error", "stack trace",
            "python", "javascript", "typescript", "sql", "refactor",
        ]
    )
    reasoning_keywords: list[str] = Field(
        default_factory=lambda: ["reason", "step by step", "prove", "analyze", "compare", "why"]
    )
    simple_keywords: list[str] = Field(
        default_factory=lambda: ["quick", "brief", "simple", "short answer", "tldr"]
    )
    technical_keywords: list[str] = Field(
        default_factory=lambda: [
            "architecture", "distributed", "latency", "throughput", "protocol",
            "complexity", "optimization", "tradeoff",
        ]
    )
    creative_keywords: list[str] = Field(
        default_factory=lambda: ["story", "poem", "creative", "brainstorm", "rewrite", "tone"]
    )

    imperative_verbs: list[str] = Field(
        default_factory=lambda: ["build", "implement", "design", "create", "generate", "optimize"]
    )
    constraint_indicators: list[str] = Field(
        default_factory=lambda: ["must", "should", "cannot", "don't", "without", "under", "limit", "constraint"]
    )
    output_format_keywords: list[str] = Field(
        default_factory=lambda: ["json", "table", "markdown", "yaml", "csv", "bullet points", "format"]
    )
    reference_keywords: list[str] = Field(
        default_factory=lambda: ["cite", "reference", "source", "link", "paper", "documentation"]
    )
    negation_keywords: list[str] = Field(
        default_factory=lambda: ["not", "never", "avoid", "exclude", "without"]
    )
    domain_specific_keywords: list[str] = Field(
        default_factory=lambda: [
            "kubernetes", "terraform", "postgres", "redis", "pydantic", "litellm",
            "oauth", "grpc", "cuda", "vector database",
        ]
    )
    agentic_task_keywords: list[str] = Field(
        default_factory=lambda: [
            "plan", "execute", "iterate", "multi-step", "autonomous", "workflow",
            "orchestrate", "tool call", "agent",
        ]
    )

    dimension_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "tokenCount": 0.08,
            "codePresence": 0.14,
            "reasoningMarkers": 0.14,
            "technicalTerms": 0.08,
            "creativeMarkers": 0.04,
            "simpleIndicators": 0.16,
            "multiStepPatterns": 0.06,
            "questionComplexity": 0.05,
            "imperativeVerbs": 0.05,
            "constraintCount": 0.05,
            "outputFormat": 0.04,
            "referenceComplexity": 0.03,
            "negationComplexity": 0.03,
            "domainSpecificity": 0.05,
            "agenticTask": 0.10,
        }
    )
    tier_boundaries: TierBoundariesConfig = Field(default_factory=TierBoundariesConfig)
    confidence_steepness: float = 5.0
    confidence_threshold: float = 0.62


class RoutingTierTargetConfig(Base):
    """Primary+fallback routing targets for one tier."""
    primary: ModelProviderConfig
    fallback: list[ModelProviderConfig] = Field(default_factory=list)


class RoutingTiersConfig(Base):
    """Tier-to-target mapping."""
    simple: RoutingTierTargetConfig | None = None
    medium: RoutingTierTargetConfig | None = None
    complex: RoutingTierTargetConfig | None = None
    reasoning: RoutingTierTargetConfig | None = None


class ModelRoutingConfig(Base):
    """Model routing and fallback configuration."""
    enabled: bool = True
    fallbacks: list[ModelProviderConfig] = Field(default_factory=list)
    scoring: RoutingScoringConfig = Field(default_factory=RoutingScoringConfig)
    tiers: RoutingTiersConfig = Field(default_factory=RoutingTiersConfig)


class AgentsConfig(Base):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)
    routing: ModelRoutingConfig = Field(default_factory=ModelRoutingConfig)


class ProviderConfig(Base):
    """LLM provider configuration."""

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # Custom headers (e.g. APP-Code for AiHubMix)


class ProvidersConfig(Base):
    """Configuration for LLM providers."""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)  # Any OpenAI-compatible endpoint
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    kilo: ProviderConfig = Field(default_factory=ProviderConfig)  # Kilo AI API gateway
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)  # 阿里云通义千问
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)  # AiHubMix API gateway
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)  # SiliconFlow (硅基流动) API gateway
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)  # VolcEngine (火山引擎) API gateway
    openai_codex: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenAI Codex (OAuth)
    github_copilot: ProviderConfig = Field(default_factory=ProviderConfig)  # Github Copilot (OAuth)


class GatewayConfig(Base):
    """Gateway/server configuration."""

    host: str = "0.0.0.0"
    port: int = 18790


class WebSearchConfig(Base):
    """Web search tool configuration."""

    api_key: str = ""  # Brave Search API key
    tavily_api_key: str = ""  # Tavily API key (fallback)
    max_results: int = 5


class WebToolsConfig(Base):
    """Web tools configuration."""

    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Shell exec tool configuration."""

    timeout: int = 60


class MCPServerConfig(Base):
    """MCP server connection configuration (stdio or HTTP)."""

    command: str = ""  # Stdio: command to run (e.g. "npx")
    args: list[str] = Field(default_factory=list)  # Stdio: command arguments
    env: dict[str, str] = Field(default_factory=dict)  # Stdio: extra env vars
    url: str = ""  # HTTP: streamable HTTP endpoint URL
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP: Custom HTTP Headers
    tool_timeout: int = 30  # Seconds before a tool call is cancelled


class ToolsConfig(Base):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # If true, restrict all tool access to workspace directory
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class Config(BaseSettings):
    """Root configuration for nanobot."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    @staticmethod
    def _normalize_provider_name(provider_name: str | None) -> str | None:
        """Normalize provider identifiers like `openai-codex` -> `openai_codex`."""
        if not provider_name:
            return None
        name = provider_name.strip().lower().replace("-", "_")
        return name or None

    def _match_provider(self, model: str | None = None) -> tuple["ProviderConfig | None", str | None]:
        """Match provider config and its registry name. Returns (config, spec_name)."""
        from nanobot.providers.registry import PROVIDERS

        model_lower = (model or self.agents.defaults.model).lower()
        model_normalized = model_lower.replace("-", "_")
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")
        default_model = self.agents.defaults.model.lower()
        explicit_default_provider = self._normalize_provider_name(self.agents.defaults.provider)

        # Explicit defaults.provider wins for defaults.model resolution.
        if explicit_default_provider and (model is None or model_lower == default_model):
            p = getattr(self.providers, explicit_default_provider, None)
            if p is not None:
                return p, explicit_default_provider

        def _kw_matches(kw: str) -> bool:
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # Explicit provider prefix wins — prevents `github-copilot/...codex` matching openai_codex.
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                if spec.is_oauth or p.api_key:
                    return p, spec.name

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                if spec.is_oauth or p.api_key:
                    return p, spec.name

        # Fallback: gateways first, then others (follows registry order)
        # OAuth providers are NOT valid fallbacks — they require explicit model selection
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Get matched provider config (api_key, api_base, extra_headers). Falls back to first available."""
        p, _ = self._match_provider(model)
        return p

    def get_provider_by_name(self, provider_name: str) -> ProviderConfig | None:
        """Get provider config by explicit provider name from config."""
        normalized = self._normalize_provider_name(provider_name)
        if not normalized:
            return None
        return getattr(self.providers, normalized, None)

    def get_provider_name(self, model: str | None = None) -> str | None:
        """Get the registry name of the matched provider (e.g. "deepseek", "openrouter")."""
        _, name = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL for the given model. Applies default URLs for known gateways."""
        from nanobot.providers.registry import find_by_name

        p, name = self._match_provider(model)
        if p and p.api_base:
            return p.api_base
        # Only gateways get a default api_base here. Standard providers
        # (like Moonshot) set their base URL via env vars in _setup_env
        # to avoid polluting the global litellm.api_base.
        if name:
            spec = find_by_name(name)
            if spec and spec.is_gateway and spec.default_api_base:
                return spec.default_api_base
        return None

    def get_api_base_for_provider(self, provider_name: str, model: str | None = None) -> str | None:
        """Get API base URL for an explicit provider name."""
        from nanobot.providers.registry import find_by_name
        normalized = self._normalize_provider_name(provider_name)
        if not normalized:
            return None

        p = self.get_provider_by_name(normalized)
        if p and p.api_base:
            return p.api_base

        spec = find_by_name(normalized)
        if spec and spec.default_api_base:
            return spec.default_api_base

        # Fallback to model-based matching if provider has no registry default.
        if model:
            return self.get_api_base(model)
        return None

    model_config = ConfigDict(env_prefix="NANOBOT_", env_nested_delimiter="__")
