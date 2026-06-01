"""Shared preset helpers for generating client-scoped runtime profiles."""

from __future__ import annotations

from typing import Literal

from clawteam.config import AgentPreset, AgentProfile, load_config

PresetSource = Literal["builtin", "local"]


def builtin_presets() -> dict[str, AgentPreset]:
    """Return built-in preset catalog."""
    def claude_compatible_preset(
        description: str,
        auth_env: str,
        base_url: str,
        model: str,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> AgentPreset:
        env = {
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        }
        if extra_env:
            env.update(extra_env)
        return AgentPreset(
            description=description,
            auth_env=auth_env,
            client_overrides={
                "claude": AgentProfile(
                    agent="claude",
                    model=model,
                    base_url=base_url,
                    env=env,
                )
            },
        )

    return {
        "anthropic-official": AgentPreset(
            description="Official Claude Code setup using direct Anthropic auth.",
            auth_env="ANTHROPIC_API_KEY",
            client_overrides={
                "claude": AgentProfile(
                    agent="claude",
                    model="sonnet",
                )
            },
        ),
        "openai-official": AgentPreset(
            description="Official Codex setup using OpenAI auth.",
            auth_env="OPENAI_API_KEY",
            client_overrides={
                "codex": AgentProfile(
                    agent="codex",
                    model="gpt-5.4",
                )
            },
        ),
        "google-ai-studio": AgentPreset(
            description="Official Gemini CLI setup using a Gemini API key from Google AI Studio.",
            auth_env="GEMINI_API_KEY",
            client_overrides={
                "gemini": AgentProfile(
                    agent="gemini",
                    model="gemini-2.5-pro",
                )
            },
        ),
        "moonshot-cn": AgentPreset(
            description="Moonshot China endpoints for Claude-compatible Kimi and native Kimi CLI.",
            auth_env="MOONSHOT_API_KEY",
            client_overrides={
                "claude": AgentProfile(
                    agent="claude",
                    model="kimi-k2.5",
                    base_url="https://api.moonshot.cn/anthropic",
                    env={
                        "ANTHROPIC_MODEL": "kimi-k2.5",
                        "ANTHROPIC_DEFAULT_OPUS_MODEL": "kimi-k2.5",
                        "ANTHROPIC_DEFAULT_SONNET_MODEL": "kimi-k2.5",
                        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "kimi-k2.5",
                        "CLAUDE_CODE_SUBAGENT_MODEL": "kimi-k2.5",
                        "ENABLE_TOOL_SEARCH": "false",
                    },
                ),
                "kimi": AgentProfile(
                    agent="kimi",
                    model="kimi-k2-thinking-turbo",
                    base_url="https://api.moonshot.cn/v1",
                ),
            },
        ),
        "deepseek": claude_compatible_preset(
            "DeepSeek via Anthropic-compatible Claude Code endpoint.",
            "DEEPSEEK_API_KEY",
            "https://api.deepseek.com/anthropic",
            "DeepSeek-V3.2",
        ),
        "zhipu-cn": claude_compatible_preset(
            "Zhipu GLM via the mainland China Anthropic-compatible endpoint.",
            "ZHIPU_API_KEY",
            "https://open.bigmodel.cn/api/anthropic",
            "glm-5",
        ),
        "zhipu-global": claude_compatible_preset(
            "Zhipu GLM via the global Anthropic-compatible endpoint.",
            "ZHIPU_API_KEY",
            "https://api.z.ai/api/anthropic",
            "glm-5",
        ),
        "bailian": AgentPreset(
            description="Alibaba Bailian Claude-compatible endpoint.",
            auth_env="DASHSCOPE_API_KEY",
            client_overrides={
                "claude": AgentProfile(
                    agent="claude",
                    base_url="https://dashscope.aliyuncs.com/apps/anthropic",
                )
            },
        ),
        "bailian-coding": AgentPreset(
            description="Alibaba Bailian coding endpoint for Claude Code.",
            auth_env="DASHSCOPE_API_KEY",
            client_overrides={
                "claude": AgentProfile(
                    agent="claude",
                    base_url="https://coding.dashscope.aliyuncs.com/apps/anthropic",
                )
            },
        ),
        "minimax-cn": claude_compatible_preset(
            "MiniMax China Anthropic-compatible Claude Code endpoint.",
            "MINIMAX_API_KEY",
            "https://api.minimaxi.com/anthropic",
            "MiniMax-M3",
            extra_env={
                "API_TIMEOUT_MS": "3000000",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
        ),
        "minimax-global": claude_compatible_preset(
            "MiniMax global Anthropic-compatible Claude Code endpoint.",
            "MINIMAX_API_KEY",
            "https://api.minimax.io/anthropic",
            "MiniMax-M3",
            extra_env={
                "API_TIMEOUT_MS": "3000000",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
        ),
        "openrouter": AgentPreset(
            description="OpenRouter preset spanning Claude Code, Codex, and Gemini CLI.",
            auth_env="OPENROUTER_API_KEY",
            client_overrides={
                "claude": AgentProfile(
                    agent="claude",
                    model="anthropic/claude-sonnet-4.6",
                    base_url="https://openrouter.ai/api",
                    env={
                        "ANTHROPIC_MODEL": "anthropic/claude-sonnet-4.6",
                        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "anthropic/claude-haiku-4.5",
                        "ANTHROPIC_DEFAULT_SONNET_MODEL": "anthropic/claude-sonnet-4.6",
                        "ANTHROPIC_DEFAULT_OPUS_MODEL": "anthropic/claude-opus-4.6",
                    },
                ),
                "codex": AgentProfile(
                    agent="codex",
                    model="openai/gpt-5.4",
                    base_url="https://openrouter.ai/api/v1",
                ),
                "gemini": AgentProfile(
                    agent="gemini",
                    model="google/gemini-2.5-pro",
                    base_url="https://openrouter.ai/api",
                ),
            },
        ),
        "gemini-vertex": AgentPreset(
            description="Gemini CLI using Vertex ADC and local gcloud credentials.",
            env={
                "GOOGLE_GENAI_USE_VERTEXAI": "true",
                "GOOGLE_CLOUD_LOCATION": "global",
            },
            client_overrides={
                "gemini": AgentProfile(
                    agent="gemini",
                    model="gemini-2.5-flash",
                )
            },
        ),
    }


def list_presets() -> dict[str, tuple[AgentPreset, PresetSource]]:
    """Return combined preset catalog with source annotations."""
    combined = {name: (preset, "builtin") for name, preset in builtin_presets().items()}
    for name, preset in load_config().presets.items():
        combined[name] = (preset, "local")
    return combined


def load_preset(name: str) -> tuple[AgentPreset, PresetSource]:
    """Load a preset by name from local config or built-ins."""
    preset = list_presets().get(name)
    if preset is None:
        raise ValueError(f"Unknown preset '{name}'")
    return preset


def save_preset(name: str, preset: AgentPreset) -> None:
    """Persist a local preset."""
    from clawteam.config import save_config

    cfg = load_config()
    cfg.presets[name] = preset
    save_config(cfg)


def editable_preset(name: str) -> AgentPreset:
    """Return a local editable preset, cloning a built-in when needed."""
    cfg = load_config()
    local = cfg.presets.get(name)
    if local is not None:
        return local.model_copy(deep=True)
    builtin = builtin_presets().get(name)
    if builtin is not None:
        return builtin.model_copy(deep=True)
    return AgentPreset()


def remove_preset(name: str) -> bool:
    """Remove a locally configured preset."""
    from clawteam.config import save_config

    cfg = load_config()
    if name not in cfg.presets:
        return False
    del cfg.presets[name]
    save_config(cfg)
    return True


def copy_preset(source_name: str, target_name: str) -> AgentPreset:
    """Copy a built-in or local preset into a new local preset."""
    preset, _ = load_preset(source_name)
    copied = preset.model_copy(deep=True)
    save_preset(target_name, copied)
    return copied


def save_preset_client(name: str, client: str, profile: AgentProfile) -> AgentPreset:
    """Create or update a single client override inside a local preset."""
    preset = load_config().presets.get(name, AgentPreset())
    preset = preset.model_copy(deep=True)
    preset.client_overrides[_normalize_client(client)] = profile
    save_preset(name, preset)
    return preset


def remove_preset_client(name: str, client: str) -> bool:
    """Remove a single client override from a local preset."""
    from clawteam.config import save_config

    cfg = load_config()
    preset = cfg.presets.get(name)
    normalized = _normalize_client(client)
    if preset is None or normalized not in preset.client_overrides:
        return False
    preset = preset.model_copy(deep=True)
    del preset.client_overrides[normalized]
    cfg.presets[name] = preset
    save_config(cfg)
    return True


def generate_profile_from_preset(
    preset_name: str,
    client: str,
    *,
    name: str | None = None,
) -> tuple[str, AgentProfile]:
    """Generate a client-scoped profile from a preset."""
    preset, _ = load_preset(preset_name)
    normalized_client = _normalize_client(client)
    override = preset.client_overrides.get(normalized_client)
    if override is None:
        raise ValueError(
            f"Preset '{preset_name}' does not define a client override for '{normalized_client}'"
        )

    profile = override.model_copy(deep=True)
    if not profile.command and not profile.agent:
        profile.agent = normalized_client
    if preset.description and not profile.description:
        profile.description = preset.description
    if preset.base_url and not profile.base_url:
        profile.base_url = preset.base_url
    if preset.auth_env and not profile.api_key_env:
        profile.api_key_env = preset.auth_env
    if preset.env:
        merged_env = dict(preset.env)
        merged_env.update(profile.env)
        profile.env = merged_env

    return name or f"{normalized_client}-{preset_name}", profile


def preset_clients(preset: AgentPreset) -> list[str]:
    """Return sorted client names configured by a preset."""
    return sorted(preset.client_overrides.keys())


def _normalize_client(client: str) -> str:
    normalized = client.strip().lower()
    aliases = {
        "claude-code": "claude",
        "codex-cli": "codex",
    }
    return aliases.get(normalized, normalized)
