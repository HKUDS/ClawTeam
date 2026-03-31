"""CLI commands for clawteam - framework-agnostic multi-agent coordination."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from clawteam import __version__
from clawteam.timefmt import format_timestamp

app = typer.Typer(
    name="clawteam",
    help="Framework-agnostic multi-agent coordination CLI",
    no_args_is_help=True,
)
console = Console()


# ---------------------------------------------------------------------------
# Global options via callback
# ---------------------------------------------------------------------------

_json_output: bool = False
_data_dir: str | None = None


def _version_callback(value: bool):
    if value:
        console.print(f"clawteam v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Output JSON instead of human-readable text.",
    ),
    data_dir: Optional[str] = typer.Option(
        None, "--data-dir", help="Override data directory (default: ~/.clawteam).",
    ),
    transport: Optional[str] = typer.Option(
        None, "--transport", help="Transport backend: file or p2p.",
    ),
):
    """clawteam - Framework-agnostic multi-agent coordination CLI."""
    global _json_output, _data_dir
    _json_output = json_out
    if data_dir:
        import os
        os.environ["CLAWTEAM_DATA_DIR"] = data_dir
        _data_dir = data_dir
    if transport:
        import os
        os.environ["CLAWTEAM_TRANSPORT"] = transport


def _dump(model) -> dict:
    """Dump a pydantic model to dict with by_alias and exclude_none."""
    return json.loads(model.model_dump_json(by_alias=True, exclude_none=True))


def _output(data: dict | list, human_fn=None):
    """Output data as JSON or human-readable."""
    if _json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif human_fn:
        human_fn(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def _spawn_backend_hint(backend: str | None, team: str | None) -> str:
    """Return a helpful hint when spawn positional args are misordered."""
    if not backend or team:
        return ""
    return (
        " Hint: the first positional argument to `clawteam spawn` is the backend "
        "(`tmux` or `subprocess`), not the team name. Use `--team <name>` to set "
        "the team explicitly."
    )


def _load_skill_content(name: str) -> str | None:
    """Load skill content from ~/.claude/skills.

    Supports both directory format (skills/<name>/SKILL.md) and
    single-file format (skills/<name>.md).
    """
    skills_root = Path.home() / ".claude" / "skills"
    skill_dir = skills_root / name
    if skill_dir.is_dir():
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            markdown_files = sorted(skill_dir.glob("*.md"))
            skill_file = markdown_files[0] if markdown_files else None
        if skill_file and skill_file.exists():
            return skill_file.read_text(encoding="utf-8")

    single_file = skills_root / f"{name}.md"
    if single_file.exists():
        return single_file.read_text(encoding="utf-8")
    return None


def _parse_key_value_items(items: list[str], *, label: str) -> dict[str, str]:
    """Parse repeated KEY=VALUE CLI options into a dict."""
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            console.print(f"[red]Invalid {label} '{item}'. Expected KEY=VALUE.[/red]")
            raise typer.Exit(1)
        key, value = item.split("=", 1)
        if not key:
            console.print(f"[red]Invalid {label} '{item}'. Key cannot be empty.[/red]")
            raise typer.Exit(1)
        parsed[key] = value
    return parsed


def _load_questionary():
    """Import questionary lazily so non-TUI flows do not depend on it at runtime."""
    try:
        import questionary
    except ImportError as exc:  # pragma: no cover - import error path is trivial
        console.print(
            "[red]Questionary is not installed. Reinstall ClawTeam with its default "
            "dependencies to use `clawteam profile wizard`.[/red]"
        )
        raise typer.Exit(1) from exc
    return questionary


def _profile_wizard_style(questionary):
    return questionary.Style(
        [
            ("qmark", "fg:#22c55e bold"),
            ("question", "bold"),
            ("answer", "fg:#38bdf8 bold"),
            ("pointer", "fg:#f59e0b bold"),
            ("highlighted", "fg:#f59e0b bold"),
            ("selected", "fg:#22c55e"),
            ("instruction", "fg:#94a3b8 italic"),
        ]
    )


def _questionary_safe_ask(control):
    answer = control.ask()
    if answer is None:
        console.print("[yellow]Cancelled.[/yellow]")
        raise typer.Exit(1)
    return answer


# ============================================================================
# Config Commands
# ============================================================================

config_app = typer.Typer(help="Configuration management")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show():
    """Show all configuration settings and their sources."""
    from clawteam.config import get_effective, scalar_config_keys

    keys = scalar_config_keys()
    data = {}
    for k in keys:
        val, source = get_effective(k)
        data[k] = {"value": val, "source": source}

    def _human(d):
        table = Table(title="Configuration")
        table.add_column("Key", style="cyan")
        table.add_column("Value")
        table.add_column("Source", style="dim")
        for k in keys:
            v = d[k]["value"]
            table.add_row(k, str(v) if v != "" else "(empty)", d[k]["source"])
        console.print(table)

    _output(data, _human)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(
        ...,
        help="Config key (e.g. data_dir, user, transport, workspace, default_backend, skip_permissions, gource_path)",
    ),
    value: str = typer.Argument(..., help="Config value"),
):
    """Persistently set a configuration value."""
    from clawteam.config import ClawTeamConfig, load_config, save_config, scalar_config_keys

    valid_keys = set(scalar_config_keys())
    if key not in valid_keys:
        console.print(f"[red]Invalid key '{key}'. Valid: {', '.join(sorted(valid_keys))}[/red]")
        raise typer.Exit(1)

    cfg = load_config()
    field_info = ClawTeamConfig.model_fields[key]
    if field_info.annotation is bool:
        setattr(cfg, key, value.lower() in ("true", "1", "yes"))
    else:
        setattr(cfg, key, value)
    save_config(cfg)

    _output(
        {"status": "saved", "key": key, "value": value},
        lambda d: console.print(f"[green]OK[/green] {key} = {value}"),
    )


@config_app.command("get")
def config_get(
    key: str = typer.Argument(
        ...,
        help="Config key (e.g. data_dir, user, transport, workspace, default_backend, skip_permissions, gource_path)",
    ),
):
    """Get the effective value of a config key."""
    from clawteam.config import get_effective, scalar_config_keys

    valid_keys = set(scalar_config_keys())
    if key not in valid_keys:
        console.print(f"[red]Invalid key '{key}'. Valid: {', '.join(sorted(valid_keys))}[/red]")
        raise typer.Exit(1)

    val, source = get_effective(key)
    _output(
        {"key": key, "value": val, "source": source},
        lambda d: console.print(f"{key} = {val or '(empty)'}  [dim]({source})[/dim]"),
    )


# ============================================================================
# Profile Commands
# ============================================================================

preset_app = typer.Typer(help="Shared endpoint presets for generating client-scoped profiles")
app.add_typer(preset_app, name="preset")

profile_app = typer.Typer(help="Reusable agent runtime profiles")
app.add_typer(profile_app, name="profile")


@preset_app.command("list")
def preset_list():
    """List built-in and local presets."""
    from clawteam.spawn.presets import list_presets

    presets = list_presets()

    def _human(data):
        if not data:
            console.print("[dim]No presets configured.[/dim]")
            return
        table = Table(title="Presets")
        table.add_column("Name", style="cyan")
        table.add_column("Source")
        table.add_column("Clients")
        table.add_column("Auth Env")
        table.add_column("Base URL")
        table.add_column("Description")
        for name, item in sorted(data.items()):
            preset = item["preset"]
            table.add_row(
                name,
                item["source"],
                ", ".join(sorted(preset.get("client_overrides", {}).keys())) or "(none)",
                preset.get("auth_env", "") or "(unset)",
                preset.get("base_url", "") or "(default)",
                preset.get("description", "") or "",
            )
        console.print(table)

    _output(
        {
            name: {"preset": _dump(preset), "source": source}
            for name, (preset, source) in presets.items()
        },
        _human,
    )


@preset_app.command("show")
def preset_show(
    name: str = typer.Argument(..., help="Preset name"),
):
    """Show a single preset."""
    from clawteam.spawn.presets import load_preset

    try:
        preset, source = load_preset(name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    data = {"preset": _dump(preset), "source": source}

    def _human(d):
        preset = d["preset"]
        console.print(f"[bold cyan]{name}[/bold cyan]  [dim]({d['source']})[/dim]")
        console.print(f"  Description: {preset.get('description') or ''}")
        console.print(f"  Auth env: {preset.get('auth_env') or '(unset)'}")
        console.print(f"  Base URL: {preset.get('base_url') or '(default)'}")
        if preset.get("env"):
            console.print("  Shared env:")
            for key, value in sorted(preset["env"].items()):
                console.print(f"    {key}={value}")
        if preset.get("client_overrides"):
            console.print("  Client overrides:")
            for client, profile in sorted(preset["client_overrides"].items()):
                command = " ".join(profile.get("command", [])) or profile.get("agent") or "(unset)"
                model = profile.get("model") or "(default)"
                base_url = profile.get("base_url") or preset.get("base_url") or "(default)"
                console.print(f"    {client}: {command} | model={model} | base_url={base_url}")

    _output(data, _human)


@preset_app.command("set")
def preset_set(
    name: str = typer.Argument(..., help="Preset name"),
    description: Optional[str] = typer.Option(None, "--description", help="Preset description"),
    auth_env: Optional[str] = typer.Option(None, "--auth-env", help="Default source env var holding provider auth"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Default base URL shared by clients"),
    env: list[str] = typer.Option(None, "--env", help="Shared env assignment KEY=VALUE"),
):
    """Create or update a shared preset."""
    from clawteam.spawn.presets import editable_preset, save_preset

    preset = editable_preset(name)
    if description is not None:
        preset.description = description
    if auth_env is not None:
        preset.auth_env = auth_env
    if base_url is not None:
        preset.base_url = base_url
    if env:
        preset.env = _parse_key_value_items(env, label="env")

    save_preset(name, preset)
    _output(
        {"status": "saved", "preset": name},
        lambda d: console.print(f"[green]OK[/green] Saved preset '{name}'"),
    )


@preset_app.command("set-client")
def preset_set_client(
    preset_name: str = typer.Argument(..., help="Preset name"),
    client: str = typer.Argument(..., help="Client name (claude/codex/gemini/kimi)"),
    agent: Optional[str] = typer.Option(None, "--agent", help="Default client CLI name"),
    description: Optional[str] = typer.Option(None, "--description", help="Client-specific description"),
    command: Optional[str] = typer.Option(None, "--command", help="Exact command string"),
    model: Optional[str] = typer.Option(None, "--model", help="Default model"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Client-specific base URL override"),
    base_url_env: Optional[str] = typer.Option(None, "--base-url-env", help="Destination env var for base URL injection"),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="Client-specific source env var override"),
    api_key_target_env: Optional[str] = typer.Option(None, "--api-key-target-env", help="Destination env var receiving the resolved API key"),
    env: list[str] = typer.Option(None, "--env", help="Static env assignment KEY=VALUE"),
    env_map: list[str] = typer.Option(None, "--env-map", help="Runtime env mapping DEST=SOURCE_ENV"),
    arg: list[str] = typer.Option(None, "--arg", help="Extra argument appended to the agent command"),
):
    """Create or update a client override inside a preset."""
    from clawteam.config import AgentProfile
    from clawteam.spawn.presets import editable_preset, save_preset

    preset = editable_preset(preset_name)
    normalized_client = client.strip().lower().replace("claude-code", "claude").replace("codex-cli", "codex")
    existing = preset.client_overrides.get(normalized_client, AgentProfile())
    profile = existing.model_copy(deep=True)

    if agent is not None:
        profile.agent = agent
    if description is not None:
        profile.description = description
    if command is not None:
        profile.command = shlex.split(command)
    if model is not None:
        profile.model = model
    if base_url is not None:
        profile.base_url = base_url
    if base_url_env is not None:
        profile.base_url_env = base_url_env
    if api_key_env is not None:
        profile.api_key_env = api_key_env
    if api_key_target_env is not None:
        profile.api_key_target_env = api_key_target_env
    if env:
        profile.env = _parse_key_value_items(env, label="env")
    if env_map:
        profile.env_map = _parse_key_value_items(env_map, label="env-map")
    if arg:
        profile.args = list(arg)
    if not profile.command and not profile.agent:
        profile.agent = normalized_client

    preset.client_overrides[normalized_client] = profile
    save_preset(preset_name, preset)
    _output(
        {"status": "saved", "preset": preset_name, "client": normalized_client},
        lambda d: console.print(
            f"[green]OK[/green] Saved client override '{normalized_client}' in preset '{preset_name}'"
        ),
    )


@preset_app.command("copy")
def preset_copy(
    source: str = typer.Argument(..., help="Source preset"),
    target: str = typer.Argument(..., help="Target local preset name"),
):
    """Copy a built-in or local preset into a new local preset."""
    from clawteam.spawn.presets import copy_preset, list_presets

    if target in list_presets():
        console.print(f"[red]Preset '{target}' already exists.[/red]")
        raise typer.Exit(1)

    try:
        copy_preset(source, target)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    _output(
        {"status": "copied", "source": source, "target": target},
        lambda d: console.print(
            f"[green]OK[/green] Copied preset '{source}' to '{target}'"
        ),
    )


@preset_app.command("remove")
def preset_remove(
    name: str = typer.Argument(..., help="Local preset name"),
):
    """Remove a locally configured preset."""
    from clawteam.spawn.presets import remove_preset

    if not remove_preset(name):
        console.print(
            f"[red]Local preset '{name}' not found.[/red] [dim](Built-ins cannot be removed.)[/dim]"
        )
        raise typer.Exit(1)

    _output(
        {"status": "removed", "preset": name},
        lambda d: console.print(f"[green]OK[/green] Removed preset '{name}'"),
    )


@preset_app.command("remove-client")
def preset_remove_client(
    preset_name: str = typer.Argument(..., help="Preset name"),
    client: str = typer.Argument(..., help="Client name"),
):
    """Remove a single client override from a local preset."""
    from clawteam.spawn.presets import remove_preset_client

    if not remove_preset_client(preset_name, client):
        console.print(
            f"[red]Client override '{client}' not found in local preset '{preset_name}'.[/red]"
        )
        raise typer.Exit(1)

    _output(
        {"status": "removed", "preset": preset_name, "client": client},
        lambda d: console.print(
            f"[green]OK[/green] Removed client override '{client}' from preset '{preset_name}'"
        ),
    )


@preset_app.command("generate-profile")
def preset_generate_profile(
    preset_name: str = typer.Argument(..., help="Preset name"),
    client: str = typer.Argument(..., help="Client name"),
    name: Optional[str] = typer.Option(None, "--name", help="Target profile name (default: <client>-<preset>)"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing profile"),
):
    """Generate a single profile from a preset."""
    from clawteam.spawn.presets import generate_profile_from_preset
    from clawteam.spawn.profiles import list_profiles, save_profile

    try:
        profile_name, profile = generate_profile_from_preset(preset_name, client, name=name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if profile_name in list_profiles() and not force:
        console.print(
            f"[red]Profile '{profile_name}' already exists. Use --force to overwrite.[/red]"
        )
        raise typer.Exit(1)

    save_profile(profile_name, profile)
    _output(
        {"status": "saved", "profile": profile_name, "preset": preset_name, "client": client},
        lambda d: console.print(
            f"[green]OK[/green] Generated profile '{profile_name}' from preset '{preset_name}' for client '{client}'"
        ),
    )


@preset_app.command("bootstrap")
def preset_bootstrap(
    preset_name: str = typer.Argument(..., help="Preset name"),
    client: list[str] = typer.Option(None, "--client", help="Client to generate (repeatable). Defaults to all clients defined by the preset"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing profiles"),
):
    """Generate one profile per client from a preset."""
    from clawteam.spawn.presets import generate_profile_from_preset, load_preset, preset_clients
    from clawteam.spawn.profiles import list_profiles, save_profile

    try:
        preset, _ = load_preset(preset_name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    clients = client or preset_clients(preset)
    if not clients:
        console.print(f"[red]Preset '{preset_name}' does not define any clients.[/red]")
        raise typer.Exit(1)

    existing_profiles = list_profiles()
    generated: list[str] = []
    skipped: list[str] = []

    for item in clients:
        try:
            profile_name, profile = generate_profile_from_preset(preset_name, item)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        if profile_name in existing_profiles and not force:
            skipped.append(profile_name)
            continue
        save_profile(profile_name, profile)
        generated.append(profile_name)

    data = {
        "preset": preset_name,
        "generated": generated,
        "skipped": skipped,
    }

    def _human(d):
        if d["generated"]:
            console.print(
                f"[green]OK[/green] Generated profiles from '{preset_name}': {', '.join(d['generated'])}"
            )
        if d["skipped"]:
            console.print(
                f"[yellow]Skipped existing profiles[/yellow]: {', '.join(d['skipped'])}"
            )

    _output(data, _human)


@profile_app.command("list")
def profile_list():
    """List configured agent profiles."""
    from clawteam.spawn.profiles import list_profiles

    profiles = list_profiles()

    def _human(data):
        if not data:
            console.print("[dim]No profiles configured.[/dim]")
            return
        table = Table(title="Profiles")
        table.add_column("Name", style="cyan")
        table.add_column("Agent")
        table.add_column("Model")
        table.add_column("Base URL")
        table.add_column("Description")
        for name, profile in sorted(data.items()):
            agent = profile.get("agent") or (" ".join(profile.get("command", [])) if profile.get("command") else "")
            table.add_row(
                name,
                agent or "(unset)",
                profile.get("model", "") or "(default)",
                profile.get("base_url", "") or "(default)",
                profile.get("description", "") or "",
            )
        console.print(table)

    _output({name: _dump(profile) for name, profile in profiles.items()}, _human)


@profile_app.command("show")
def profile_show(
    name: str = typer.Argument(..., help="Profile name"),
):
    """Show a single profile."""
    from clawteam.spawn.profiles import load_profile

    try:
        profile = load_profile(name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    data = _dump(profile)

    def _human(d):
        console.print(f"[bold cyan]{name}[/bold cyan]")
        console.print(f"  Agent: {d.get('agent') or '(unset)'}")
        console.print(f"  Command: {' '.join(d.get('command', [])) or '(unset)'}")
        console.print(f"  Model: {d.get('model') or '(default)'}")
        console.print(f"  Base URL: {d.get('base_url') or '(default)'}")
        if d.get("base_url_env"):
            console.print(f"  Base URL target env: {d['base_url_env']}")
        console.print(f"  API key env: {d.get('api_key_env') or '(unset)'}")
        if d.get("api_key_target_env"):
            console.print(f"  API key target env: {d['api_key_target_env']}")
        console.print(f"  Description: {d.get('description') or ''}")
        if d.get("args"):
            console.print(f"  Extra args: {' '.join(d['args'])}")
        if d.get("env"):
            console.print("  Env:")
            for key, value in sorted(d["env"].items()):
                console.print(f"    {key}={value}")
        if d.get("env_map"):
            console.print("  Env map:")
            for key, value in sorted(d["env_map"].items()):
                console.print(f"    {key} <- ${value}")

    _output(data, _human)


@profile_app.command("set")
def profile_set(
    name: str = typer.Argument(..., help="Profile name"),
    agent: Optional[str] = typer.Option(None, "--agent", help="Default agent CLI name (claude/codex/gemini/kimi/nanobot)"),
    description: Optional[str] = typer.Option(None, "--description", help="Profile description"),
    command: Optional[str] = typer.Option(None, "--command", help="Exact command string (e.g. 'kimi --config-file ~/.kimi/config.toml')"),
    model: Optional[str] = typer.Option(None, "--model", help="Default model"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Provider base URL"),
    base_url_env: Optional[str] = typer.Option(None, "--base-url-env", help="Destination env var for base URL injection"),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="Source env var holding the API key"),
    api_key_target_env: Optional[str] = typer.Option(None, "--api-key-target-env", help="Destination env var receiving the resolved API key"),
    env: list[str] = typer.Option(None, "--env", help="Static env assignment KEY=VALUE"),
    env_map: list[str] = typer.Option(None, "--env-map", help="Runtime env mapping DEST=SOURCE_ENV"),
    arg: list[str] = typer.Option(None, "--arg", help="Extra argument appended to the agent command"),
):
    """Create or update a profile."""
    from clawteam.config import AgentProfile
    from clawteam.spawn.profiles import list_profiles, save_profile

    existing = list_profiles().get(name, AgentProfile())
    profile = existing.model_copy(deep=True)

    if agent is not None:
        profile.agent = agent
    if description is not None:
        profile.description = description
    if command is not None:
        profile.command = shlex.split(command)
    if model is not None:
        profile.model = model
    if base_url is not None:
        profile.base_url = base_url
    if base_url_env is not None:
        profile.base_url_env = base_url_env
    if api_key_env is not None:
        profile.api_key_env = api_key_env
    if api_key_target_env is not None:
        profile.api_key_target_env = api_key_target_env
    if env:
        profile.env = _parse_key_value_items(env, label="env")
    if env_map:
        profile.env_map = _parse_key_value_items(env_map, label="env-map")
    if arg:
        profile.args = list(arg)

    if not profile.command and not profile.agent:
        console.print("[red]Profile must define either --agent or --command.[/red]")
        raise typer.Exit(1)

    save_profile(name, profile)
    _output(
        {"status": "saved", "profile": name},
        lambda d: console.print(f"[green]OK[/green] Saved profile '{name}'"),
    )


@profile_app.command("remove")
def profile_remove(
    name: str = typer.Argument(..., help="Profile name"),
):
    """Remove a profile."""
    from clawteam.spawn.profiles import remove_profile

    if not remove_profile(name):
        console.print(f"[red]Unknown profile '{name}'[/red]")
        raise typer.Exit(1)

    _output(
        {"status": "removed", "profile": name},
        lambda d: console.print(f"[green]OK[/green] Removed profile '{name}'"),
    )


@profile_app.command("test")
def profile_test(
    name: str = typer.Argument(..., help="Profile name"),
    prompt: str = typer.Option("Reply with exactly CLAWTEAM_PROFILE_OK", "--prompt", help="Smoke test prompt"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Working directory for the test run"),
):
    """Run a non-interactive smoke test for a profile."""
    from clawteam.spawn.adapters import NativeCliAdapter
    from clawteam.spawn.command_validation import validate_spawn_command
    from clawteam.spawn.profiles import apply_profile, load_profile

    try:
        profile = load_profile(name)
        command, env, agent = apply_profile(profile)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    adapter = NativeCliAdapter()
    prepared = adapter.prepare_command(
        command,
        prompt=prompt,
        cwd=cwd,
        skip_permissions=True,
        interactive=False,
    )
    command_error = validate_spawn_command(prepared.normalized_command, path=os.environ.get("PATH"), cwd=cwd)
    if command_error:
        console.print(f"[red]{command_error}[/red]")
        raise typer.Exit(1)

    run_env = os.environ.copy()
    run_env.update(env)
    result = subprocess.run(
        prepared.final_command,
        cwd=cwd,
        env=run_env,
        capture_output=True,
        text=True,
    )
    data = {
        "profile": name,
        "agent": agent,
        "command": prepared.final_command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

    def _human(d):
        console.print(f"Profile: [cyan]{d['profile']}[/cyan]")
        console.print(f"Agent: [cyan]{d['agent']}[/cyan]")
        console.print(f"Command: {' '.join(shlex.quote(part) for part in d['command'])}")
        console.print(f"Return code: {d['returncode']}")
        if d["stdout"]:
            console.print("\n[bold]stdout[/bold]")
            console.print(d["stdout"].rstrip())
        if d["stderr"]:
            console.print("\n[bold]stderr[/bold]")
            console.print(d["stderr"].rstrip())

    _output(data, _human)
    if result.returncode != 0:
        raise typer.Exit(1)


@profile_app.command("wizard")
def profile_wizard():
    """Launch an interactive TUI for creating profiles from providers or manually."""
    from clawteam.config import AgentProfile
    from clawteam.spawn.presets import generate_profile_from_preset, list_presets, preset_clients
    from clawteam.spawn.profiles import list_profiles, save_profile

    questionary = _load_questionary()
    style = _profile_wizard_style(questionary)
    clients = [
        questionary.Choice("Claude Code", "claude"),
        questionary.Choice("Codex", "codex"),
        questionary.Choice("Gemini CLI", "gemini"),
        questionary.Choice("Kimi CLI", "kimi"),
        questionary.Choice("Nanobot", "nanobot"),
    ]
    preset_catalog = list_presets()

    console.print("[bold cyan]ClawTeam Profile Wizard[/bold cyan]")
    setup_mode = _questionary_safe_ask(
        questionary.select(
            "Choose a setup mode",
            choices=[
                questionary.Choice("Quick setup", "quick"),
                questionary.Choice("Advanced setup", "advanced"),
            ],
            style=style,
        )
    )
    client = _questionary_safe_ask(
        questionary.select(
            "Choose a client",
            choices=clients,
            style=style,
        )
    )

    provider_choices = []
    for preset_name, (preset, source) in sorted(preset_catalog.items()):
        if client in preset_clients(preset):
            description = preset.description or "Recommended provider setup"
            provider_choices.append(
                questionary.Choice(
                    title=f"{preset_name}  [{source}]  {description}",
                    value=preset_name,
                )
            )
    provider_choices.append(
        questionary.Choice("Custom endpoint / manual configuration", "__custom__")
    )
    provider_name = _questionary_safe_ask(
        questionary.select(
            "Choose a provider template",
            choices=provider_choices,
            style=style,
        )
    )

    if provider_name == "__custom__":
        suggested_name = f"{client}-custom"
        profile = AgentProfile(agent=client, description=f"Custom {client} profile")
    else:
        suggested_name = f"{client}-{provider_name}"
        _, profile = generate_profile_from_preset(provider_name, client, name=suggested_name)

    profile_name = _questionary_safe_ask(
        questionary.text(
            "Profile name",
            default=suggested_name,
            style=style,
        )
    )

    profile = profile.model_copy(deep=True)
    quick_known_provider = setup_mode == "quick" and provider_name != "__custom__"
    edit_recommended_settings = setup_mode == "advanced" or provider_name == "__custom__"

    if quick_known_provider:
        console.print(
            f"[dim]Using recommended settings from provider template '{provider_name}'.[/dim]"
        )
        edit_recommended_settings = _questionary_safe_ask(
            questionary.confirm(
                "Edit recommended model / endpoint / auth settings?",
                default=False,
                style=style,
            )
        )

    if not quick_known_provider or edit_recommended_settings:
        profile.description = _questionary_safe_ask(
            questionary.text(
                "Description",
                default=profile.description,
                style=style,
            )
        )
        profile.model = _questionary_safe_ask(
            questionary.text(
                "Default model",
                default=profile.model,
                style=style,
            )
        )
        profile.base_url = _questionary_safe_ask(
            questionary.text(
                "Base URL",
                default=profile.base_url,
                style=style,
            )
        )
        profile.api_key_env = _questionary_safe_ask(
            questionary.text(
                "API key env var name",
                default=profile.api_key_env,
                style=style,
            )
        )

    configure_advanced = setup_mode == "advanced"
    if setup_mode == "quick":
        configure_advanced = _questionary_safe_ask(
            questionary.confirm(
                "Open advanced options (command, args, env overrides)?",
                default=False,
                style=style,
            )
        )

    if configure_advanced:
        profile.agent = _questionary_safe_ask(
            questionary.text(
                "Agent CLI name",
                default=profile.agent or (Path(profile.command[0]).name if profile.command else ""),
                style=style,
            )
        )
        command_default = " ".join(profile.command)
        command_raw = _questionary_safe_ask(
            questionary.text(
                "Exact command override (optional)",
                default=command_default,
                style=style,
                instruction="Leave empty to use the agent CLI name.",
            )
        )
        profile.command = shlex.split(command_raw) if command_raw.strip() else []
        args_raw = _questionary_safe_ask(
            questionary.text(
                "Extra args (optional)",
                default=" ".join(profile.args),
                style=style,
                instruction="Example: --config-file ~/.kimi/config.toml",
            )
        )
        profile.args = shlex.split(args_raw) if args_raw.strip() else []

        env_assignments = dict(profile.env)
        while _questionary_safe_ask(
            questionary.confirm("Add a static env assignment?", default=False, style=style)
        ):
            key = _questionary_safe_ask(questionary.text("Env key", style=style))
            value = _questionary_safe_ask(questionary.text("Env value", style=style))
            env_assignments[key] = value
        profile.env = env_assignments

        env_map_assignments = dict(profile.env_map)
        while _questionary_safe_ask(
            questionary.confirm("Add an env mapping from an existing shell variable?", default=False, style=style)
        ):
            dest = _questionary_safe_ask(
                questionary.text("Destination env key", style=style)
            )
            source = _questionary_safe_ask(
                questionary.text("Source shell env var", style=style)
            )
            env_map_assignments[dest] = source
        profile.env_map = env_map_assignments

    if not profile.command and not profile.agent:
        console.print("[red]Profile must define either an agent CLI name or a command.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Profile preview[/bold]")
    console.print(f"  Name: {profile_name}")
    console.print(f"  Agent: {profile.agent or '(unset)'}")
    console.print(f"  Command: {' '.join(profile.command) or '(derived from agent)'}")
    console.print(f"  Model: {profile.model or '(default)'}")
    console.print(f"  Base URL: {profile.base_url or '(default)'}")
    console.print(f"  API key env: {profile.api_key_env or '(unset)'}")
    if profile.args:
        console.print(f"  Extra args: {' '.join(profile.args)}")
    if profile.env:
        console.print("  Static env:")
        for key, value in sorted(profile.env.items()):
            console.print(f"    {key}={value}")
    if profile.env_map:
        console.print("  Env map:")
        for key, value in sorted(profile.env_map.items()):
            console.print(f"    {key} <- ${value}")

    existing_profiles = list_profiles()
    if profile_name in existing_profiles:
        overwrite = _questionary_safe_ask(
            questionary.confirm(
                f"Profile '{profile_name}' already exists. Overwrite it?",
                default=False,
                style=style,
            )
        )
        if not overwrite:
            console.print("[yellow]Wizard cancelled without saving.[/yellow]")
            raise typer.Exit(1)

    save_profile(profile_name, profile)
    console.print(f"[green]OK[/green] Saved profile '{profile_name}'")

    normalized_client = (profile.agent or "").lower()
    if normalized_client in {"claude", "claude-code"}:
        if _questionary_safe_ask(
            questionary.confirm(
                "Run `clawteam profile doctor claude` now to suppress first-run onboarding?",
                default=True,
                style=style,
            )
        ):
            profile_doctor("claude")

    if _questionary_safe_ask(
        questionary.confirm("Run a smoke test for this profile now?", default=False, style=style)
    ):
        test_cwd = _questionary_safe_ask(
            questionary.text(
                "Working directory for the smoke test (optional)",
                default="",
                style=style,
            )
        )
        profile_test(profile_name, cwd=test_cwd or None)


@profile_app.command("doctor")
def profile_doctor(
    client: str = typer.Argument(..., help="Client to repair (currently: claude)"),
):
    """Repair client-specific local runtime state for profiles."""
    normalized = client.strip().lower()
    if normalized not in {"claude", "claude-code"}:
        console.print(
            f"[red]Unsupported profile doctor target '{client}'. Supported: claude[/red]"
        )
        raise typer.Exit(1)

    claude_state_path = Path.home() / ".claude.json"
    before_exists = claude_state_path.exists()
    data: dict[str, object]
    if before_exists:
        try:
            data = json.loads(claude_state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    else:
        data = {}

    data["hasCompletedOnboarding"] = True
    claude_state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    result = {
        "client": "claude",
        "path": str(claude_state_path),
        "created": not before_exists,
        "hasCompletedOnboarding": True,
    }

    def _human(d):
        action = "Created" if d["created"] else "Updated"
        console.print(
            f"[green]OK[/green] {action} Claude state at '{d['path']}' "
            "with hasCompletedOnboarding=true"
        )

    _output(result, _human)


@config_app.command("health")
def config_health():
    """Health check for the data directory (shared directory diagnostics)."""
    import os
    import time as _time

    from clawteam.config import get_effective
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import get_data_dir

    checks = {}

    # Data directory
    data_dir = get_data_dir()
    val, source = get_effective("data_dir")
    checks["data_dir"] = str(data_dir)
    checks["data_dir_source"] = source

    # Exists
    checks["exists"] = data_dir.exists()

    # Writable
    try:
        test_file = data_dir / ".health-check"
        start = _time.monotonic()
        test_file.write_text("ok", encoding="utf-8")
        content = test_file.read_text(encoding="utf-8")
        elapsed = (_time.monotonic() - start) * 1000
        test_file.unlink()
        checks["writable"] = content == "ok"
        checks["latency_ms"] = round(elapsed, 2)
    except Exception as e:
        checks["writable"] = False
        checks["latency_ms"] = -1
        checks["write_error"] = str(e)

    # Mount point check
    try:
        checks["is_mount"] = os.path.ismount(str(data_dir))
    except Exception:
        checks["is_mount"] = False

    # Teams count
    try:
        teams = TeamManager.discover_teams()
        checks["teams_count"] = len(teams)
    except Exception:
        checks["teams_count"] = 0

    # User
    user_val, user_source = get_effective("user")
    checks["user"] = user_val
    checks["user_source"] = user_source

    def _human(d):
        console.print(f"\nData Directory: [cyan]{d['data_dir']}[/cyan]  [dim]({d['data_dir_source']})[/dim]")
        console.print(f"  Exists:     {'[green]yes[/green]' if d['exists'] else '[red]no[/red]'}")
        console.print(f"  Writable:   {'[green]yes[/green]' if d['writable'] else '[red]no[/red]'}")
        if d['latency_ms'] >= 0:
            color = "green" if d['latency_ms'] < 50 else "yellow" if d['latency_ms'] < 200 else "red"
            console.print(f"  Latency:    [{color}]{d['latency_ms']:.1f} ms[/{color}]")
        console.print(f"  Mount point: {'[yellow]yes (remote/shared)[/yellow]' if d['is_mount'] else '[dim]no (local)[/dim]'}")
        console.print(f"  Teams:      {d['teams_count']}")
        console.print(f"  User:       {d['user'] or '(not set)'}  [dim]({d['user_source']})[/dim]")

    _output(checks, _human)


# ============================================================================
# Team Commands
# ============================================================================

team_app = typer.Typer(help="Team management commands")
app.add_typer(team_app, name="team")


@team_app.command("spawn-team")
def team_spawn_team(
    name: str = typer.Argument(..., help="Team name"),
    description: str = typer.Option("", "--description", "-d", help="Team description"),
    agent_name: str = typer.Option("leader", "--agent-name", "-n", help="Leader agent name"),
    agent_type: str = typer.Option("leader", "--agent-type", help="Leader agent type"),
):
    """Create a new team and register the leader (spawnTeam)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    leader_id = identity.agent_id
    leader_name = agent_name or identity.agent_name

    try:
        TeamManager.create_team(
            name=name,
            leader_name=leader_name,
            leader_id=leader_id,
            description=description,
            user=identity.user,
        )
        result = {
            "status": "created",
            "team": name,
            "leadAgentId": leader_id,
            "leaderName": leader_name,
        }
        if identity.user:
            result["user"] = identity.user
        _output(result, lambda d: (
            console.print(f"[green]OK[/green] Team '{name}' created"),
            console.print(f"  Leader: {leader_name} (id: {leader_id})"),
        ))
    except ValueError as e:
        if _json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@team_app.command("discover")
def team_discover():
    """List all teams (discoverTeams)."""
    from clawteam.team.manager import TeamManager

    teams = TeamManager.discover_teams()

    def _human(data):
        if not data:
            console.print("[dim]No teams found[/dim]")
            return
        table = Table(title="Teams")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Members", justify="right")
        for t in data:
            table.add_row(t["name"], t["description"], str(t["memberCount"]))
        console.print(table)

    _output(teams, _human)


@team_app.command("request-join")
def team_request_join(
    team: str = typer.Argument(..., help="Team name"),
    proposed_name: str = typer.Argument(..., help="Proposed agent name"),
    capabilities: str = typer.Option("", "--capabilities", "-c", help="Agent capabilities"),
    timeout: int = typer.Option(300, "--timeout", "-t", help="Timeout in seconds while waiting for leader response"),
    wait_for_response: bool = typer.Option(True, "--wait/--no-wait", help="Wait for leader approval before returning"),
):
    """Request to join a team (requestJoin). Blocks waiting for leader response."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    AgentIdentity.from_env()
    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    leader_inbox = TeamManager.get_leader_inbox(team)
    leader_name = TeamManager.get_leader_name(team)
    if not leader_name or not leader_inbox:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team)
    request_id = f"join-{uuid.uuid4().hex[:12]}"
    temp_inbox_name = f"_pending_{proposed_name}"

    mailbox.send(
        from_agent=proposed_name,
        to=leader_inbox,
        msg_type=MessageType.join_request,
        request_id=request_id,
        proposed_name=proposed_name,
        capabilities=capabilities or None,
    )

    pending_result = {
        "status": "pending",
        "requestId": request_id,
        "teamName": team,
        "proposedName": proposed_name,
    }

    if not wait_for_response:
        _output(
            pending_result,
            lambda d: console.print(
                f"[green]OK[/green] Join request sent to leader '{leader_name}'. "
                f"Request id: {d['requestId']}. Check later with "
                f"`clawteam team join-status {team} {d['requestId']} --proposed-name {proposed_name}`"
            ),
        )
        return

    if not _json_output:
        console.print(f"Join request sent to leader '{leader_name}'. Waiting for response...")

    start = time.time()
    while time.time() - start < timeout:
        messages = mailbox.receive(temp_inbox_name, limit=10)
        for msg in messages:
            if msg.request_id == request_id:
                if msg.type == MessageType.join_approved:
                    result = {
                        "status": "approved",
                        "requestId": request_id,
                        "assignedName": msg.assigned_name or proposed_name,
                        "agentId": msg.agent_id or "",
                        "teamName": team,
                    }
                    _output(result, lambda d: console.print(
                        f"[green]Approved![/green] Joined as '{d['assignedName']}'"
                    ))
                    return
                elif msg.type == MessageType.join_rejected:
                    reason = msg.reason or msg.content or ""
                    _output(
                        {"status": "rejected", "requestId": request_id, "reason": reason},
                        lambda d: console.print(f"[red]Rejected.[/red] {reason}"),
                    )
                    raise typer.Exit(1)
        time.sleep(1.0)

    _output(
        pending_result,
        lambda d: console.print(
            "[yellow]Still pending.[/yellow] The join request was sent successfully but no leader response "
            f"arrived within {timeout}s. Check later with "
            f"`clawteam team join-status {team} {d['requestId']} --proposed-name {proposed_name}`."
        ),
    )


@team_app.command("join-status")
def team_join_status(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Join request ID"),
    proposed_name: Optional[str] = typer.Option(None, "--proposed-name", help="Proposed agent name used when requesting access"),
):
    """Check the status of a join request without resubmitting it."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.models import MessageType

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    temp_inbox_name = f"_pending_{proposed_name or identity.agent_name}"
    messages = mailbox.peek(temp_inbox_name)

    for msg in messages:
        if msg.request_id != request_id:
            continue
        if msg.type == MessageType.join_approved:
            _output(
                {
                    "status": "approved",
                    "requestId": request_id,
                    "assignedName": msg.assigned_name or proposed_name or identity.agent_name,
                    "agentId": msg.agent_id or "",
                    "teamName": msg.team_name or team,
                },
                lambda d: console.print(
                    f"[green]Approved![/green] Joined as '{d['assignedName']}'"
                ),
            )
            return
        if msg.type == MessageType.join_rejected:
            _output(
                {
                    "status": "rejected",
                    "requestId": request_id,
                    "reason": msg.reason or msg.content or "",
                },
                lambda d: console.print(f"[red]Rejected.[/red] {d['reason']}"),
            )
            return

    _output(
        {
            "status": "pending",
            "requestId": request_id,
            "teamName": team,
            "proposedName": proposed_name or identity.agent_name,
        },
        lambda d: console.print(
            f"[yellow]Pending.[/yellow] No approval or rejection found yet for request '{request_id}'."
        ),
    )


@team_app.command("approve-join")
def team_approve_join(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Join request ID"),
    assigned_name: Optional[str] = typer.Option(None, "--assigned-name", help="Override proposed name"),
):
    """Approve a join request (approveJoin)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)

    leader_inbox = TeamManager.get_leader_inbox(team) or identity.agent_name
    messages = mailbox.peek(leader_inbox)
    join_req = None
    for msg in messages:
        if msg.request_id == request_id and msg.type == MessageType.join_request:
            join_req = msg
            break

    if join_req is None:
        _output(
            {"error": f"No join request found with id '{request_id}'"},
            lambda d: console.print(f"[red]Error: {d['error']}[/red]"),
        )
        raise typer.Exit(1)

    proposed_name = join_req.proposed_name
    final_name = assigned_name or proposed_name
    new_agent_id = uuid.uuid4().hex[:12]

    try:
        TeamManager.add_member(
            team_name=team,
            member_name=final_name,
            agent_id=new_agent_id,
            agent_type="general-purpose",
            user=identity.user,
        )
    except ValueError:
        pass  # already a member

    temp_inbox_name = f"_pending_{proposed_name}"
    mailbox.send(
        from_agent=identity.agent_name,
        to=temp_inbox_name,
        msg_type=MessageType.join_approved,
        request_id=request_id,
        assigned_name=final_name,
        agent_id=new_agent_id,
        team_name=team,
    )

    _output(
        {"status": "approved", "requestId": request_id, "assignedName": final_name, "agentId": new_agent_id, "teamName": team},
        lambda d: console.print(f"[green]OK[/green] Approved '{final_name}' (id: {new_agent_id})"),
    )


@team_app.command("add-member")
def team_add_member(
    team: str = typer.Argument(..., help="Team name"),
    member_name: str = typer.Argument(..., help="Member name"),
    agent_type: str = typer.Option("general-purpose", "--agent-type", help="Agent type"),
    agent_id: Optional[str] = typer.Option(None, "--agent-id", help="Agent ID (default: auto-generated)"),
):
    """Directly add a member to a team without request/approve handshake."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    resolved_agent_id = agent_id or uuid.uuid4().hex[:12]

    try:
        member = TeamManager.add_member(
            team_name=team,
            member_name=member_name,
            agent_id=resolved_agent_id,
            agent_type=agent_type,
            user=identity.user,
        )
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]Error: {d['error']}[/red]"))
        raise typer.Exit(1)

    _output(
        {"status": "added", "team": team, "member": _dump(member)},
        lambda d: console.print(
            f"[green]OK[/green] Added member '{d['member']['name']}' to team '{d['team']}'"
        ),
    )


@team_app.command("reject-join")
def team_reject_join(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Join request ID"),
    reason: str = typer.Option("", "--reason", "-r", help="Rejection reason"),
):
    """Reject a join request (rejectJoin)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)

    leader_inbox = TeamManager.get_leader_inbox(team) or identity.agent_name
    messages = mailbox.peek(leader_inbox)
    proposed_name = None
    for msg in messages:
        if msg.request_id == request_id and msg.type == MessageType.join_request:
            proposed_name = msg.proposed_name
            break

    proposed_name = proposed_name or f"agent-{request_id[:6]}"
    temp_inbox_name = f"_pending_{proposed_name}"

    mailbox.send(
        from_agent=identity.agent_name,
        to=temp_inbox_name,
        msg_type=MessageType.join_rejected,
        request_id=request_id,
        reason=reason or None,
    )

    _output(
        {"status": "rejected", "requestId": request_id, "reason": reason},
        lambda d: console.print(f"[green]OK[/green] Rejected request {request_id}"),
    )


@team_app.command("cleanup")
def team_cleanup(
    team: str = typer.Argument(..., help="Team name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a team and all its data (cleanup)."""
    from clawteam.team.manager import TeamManager

    if not force and not _json_output:
        if not typer.confirm(f"Delete team '{team}' and all its data?"):
            raise typer.Abort()

    if TeamManager.cleanup(team):
        _output({"status": "cleaned", "team": team}, lambda d: console.print(f"[green]OK[/green] Team '{team}' deleted"))
    else:
        _output({"status": "not_found", "team": team}, lambda d: console.print(f"[yellow]Team '{team}' not found[/yellow]"))


@team_app.command("status")
def team_status(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show team status and members."""
    from clawteam.team.manager import TeamManager

    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = {
        "name": config.name,
        "description": config.description,
        "leadAgentId": config.lead_agent_id,
        "createdAt": config.created_at,
        "members": [m.model_dump(by_alias=True) for m in config.members],
    }

    def _human(d):
        console.print(f"\nTeam: [cyan]{d['name']}[/cyan]")
        if d['description']:
            console.print(f"  {d['description']}")
        console.print(f"  Created: {format_timestamp(d['createdAt'])}")
        has_user = any(m.get("user") for m in d["members"])
        table = Table(title="Members")
        table.add_column("Name", style="cyan")
        if has_user:
            table.add_column("User", style="magenta")
        table.add_column("ID", style="dim")
        table.add_column("Type")
        table.add_column("Joined", style="dim")
        for m in d["members"]:
            row = [m.get("name", "")]
            if has_user:
                row.append(m.get("user", ""))
            row.extend([
                m.get("agentId", ""),
                m.get("agentType", ""),
                format_timestamp(m.get("joinedAt")),
            ])
            table.add_row(*row)
        console.print(table)

    _output(data, _human)


@team_app.command("snapshot")
def team_snapshot(
    team: str = typer.Argument(..., help="Team name"),
    tag: str = typer.Option("", "--tag", "-t", help="Label for this snapshot"),
):
    """Save a snapshot of the entire team state (config, tasks, events, sessions, costs)."""
    from clawteam.team.snapshot import SnapshotManager

    try:
        meta = SnapshotManager(team).create(tag=tag)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    data = json.loads(meta.model_dump_json(by_alias=True))

    def _human(d):
        console.print(f"[green]OK[/green] Snapshot [cyan]{d['id']}[/cyan] created")
        console.print(
            f"  {d['taskCount']} tasks, {d['eventCount']} events, "
            f"{d['sessionCount']} sessions, {d['costEventCount']} cost events"
        )

    _output(data, _human)


@team_app.command("snapshots")
def team_snapshots(
    team: str = typer.Argument(..., help="Team name"),
):
    """List available snapshots for a team."""
    from clawteam.team.snapshot import SnapshotManager

    snaps = SnapshotManager(team).list_snapshots()
    data = [json.loads(s.model_dump_json(by_alias=True)) for s in snaps]

    def _human(items):
        if not items:
            console.print("[dim]No snapshots found[/dim]")
            return
        table = Table(title=f"Snapshots for {team}")
        table.add_column("ID", style="cyan")
        table.add_column("Tag")
        table.add_column("Members", justify="right")
        table.add_column("Tasks", justify="right")
        table.add_column("Events", justify="right")
        table.add_column("Created", style="dim")
        for s in items:
            table.add_row(
                s["id"],
                s.get("tag", ""),
                str(s["memberCount"]),
                str(s["taskCount"]),
                str(s["eventCount"]),
                format_timestamp(s["createdAt"]),
            )
        console.print(table)

    _output(data, _human)


@team_app.command("restore")
def team_restore(
    team: str = typer.Argument(..., help="Team name"),
    snapshot_id: str = typer.Argument(..., help="Snapshot ID to restore"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Restore team state from a snapshot."""
    from clawteam.team.snapshot import SnapshotManager

    mgr = SnapshotManager(team)

    try:
        summary = mgr.restore(snapshot_id, dry_run=True)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if dry_run:
        _output(summary, lambda d: console.print(
            f"[yellow]Dry run[/yellow] Would restore: "
            f"{d['tasks']} tasks, {d['events']} events, "
            f"{d['sessions']} sessions, {d['costs']} costs, "
            f"{d['inboxes']} inbox messages"
        ))
        return

    if not force and not _json_output:
        console.print(
            f"Will restore: {summary['tasks']} tasks, {summary['events']} events, "
            f"{summary['sessions']} sessions, {summary['costs']} costs"
        )
        if not typer.confirm("Proceed?"):
            raise typer.Abort()

    result = mgr.restore(snapshot_id)
    _output(result, lambda d: console.print(
        f"[green]OK[/green] Restored from snapshot [cyan]{snapshot_id}[/cyan]"
    ))


@team_app.command("snapshot-delete")
def team_snapshot_delete(
    team: str = typer.Argument(..., help="Team name"),
    snapshot_id: str = typer.Argument(..., help="Snapshot ID to delete"),
):
    """Delete a snapshot."""
    from clawteam.team.snapshot import SnapshotManager

    if SnapshotManager(team).delete(snapshot_id):
        _output(
            {"status": "deleted", "id": snapshot_id},
            lambda d: console.print(f"[green]OK[/green] Snapshot '{snapshot_id}' deleted"),
        )
    else:
        console.print(f"[yellow]Snapshot '{snapshot_id}' not found[/yellow]")
        raise typer.Exit(1)


# ============================================================================
# Inbox Commands
# ============================================================================

inbox_app = typer.Typer(help="Inbox / messaging commands")
app.add_typer(inbox_app, name="inbox")


@inbox_app.command("send")
def inbox_send(
    team: str = typer.Argument(..., help="Team name"),
    to: str = typer.Argument(..., help="Recipient agent name"),
    content: str = typer.Argument(..., help="Message content"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Optional routing key"),
    msg_type: str = typer.Option("message", "--type", help="Message type"),
    from_agent: Optional[str] = typer.Option(None, "--from", "-f", help="Override sender name (default: from env identity)"),
):
    """Send a point-to-point message (write)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.models import MessageType

    sender = from_agent or AgentIdentity.from_env().agent_name
    mailbox = MailboxManager(team)
    mt = MessageType(msg_type)
    msg = mailbox.send(
        from_agent=sender,
        to=to,
        content=content,
        msg_type=mt,
        key=key,
    )
    data = _dump(msg)
    _output(data, lambda d: console.print(f"[green]OK[/green] Message sent to '{to}'"))


@inbox_app.command("broadcast")
def inbox_broadcast(
    team: str = typer.Argument(..., help="Team name"),
    content: str = typer.Argument(..., help="Message content"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Optional routing key"),
    msg_type: str = typer.Option("broadcast", "--type", help="Message type"),
    from_agent: Optional[str] = typer.Option(None, "--from", "-f", help="Override sender name (default: from env identity)"),
):
    """Broadcast a message to all team members (broadcast)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.models import MessageType

    sender = from_agent or AgentIdentity.from_env().agent_name
    mailbox = MailboxManager(team)
    mt = MessageType(msg_type)
    messages = mailbox.broadcast(
        from_agent=sender,
        content=content,
        msg_type=mt,
        key=key,
    )
    data = {"count": len(messages), "recipients": [m.to for m in messages]}
    _output(data, lambda d: console.print(f"[green]OK[/green] Broadcast to {d['count']} agents"))


@inbox_app.command("receive")
def inbox_receive(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max messages to receive"),
):
    """Receive and consume messages from inbox."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)
    messages = mailbox.receive(agent_name, limit=limit)

    data = [_dump(m) for m in messages]

    def _human(msgs):
        if not msgs:
            console.print("[dim]No messages[/dim]")
            return
        for m in msgs:
            console.print(
                f"[{format_timestamp(m.get('timestamp', ''))}] "
                f"[cyan]{m.get('type', '')}[/cyan] "
                f"from={m.get('from', '')} : {m.get('content', '')}"
            )

    _output(data, _human)


@inbox_app.command("peek")
def inbox_peek(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
):
    """Peek at messages without consuming them."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)
    messages = mailbox.peek(agent_name)

    data = {"count": len(messages), "messages": [_dump(m) for m in messages]}

    def _human(d):
        console.print(f"Pending messages: {d['count']}")
        for m in d["messages"]:
            console.print(
                f"  [{format_timestamp(m.get('timestamp', ''))}] "
                f"[cyan]{m.get('type', '')}[/cyan] "
                f"from={m.get('from', '')} : {(m.get('content') or '')[:80]}"
            )

    _output(data, _human)


@inbox_app.command("log")
def inbox_log(
    team: str = typer.Argument(..., help="Team name"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max messages to show"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by sender agent name"),
):
    """View message history (event log). Non-destructive, shows all sent messages."""
    from clawteam.team.mailbox import MailboxManager

    mailbox = MailboxManager(team)
    messages = mailbox.get_event_log(limit=limit)

    if agent:
        messages = [m for m in messages if m.from_agent == agent]

    # Reverse to show oldest first (event log returns newest first)
    messages.reverse()

    data = {"count": len(messages), "messages": [_dump(m) for m in messages]}

    def _human(d):
        console.print(f"Message history: {d['count']} message(s)")
        for m in d["messages"]:
            fr = m.get("from", "?")
            to = m.get("to", "all")
            ts = format_timestamp(m.get("timestamp") or "")
            mtype = m.get("type", "message")
            content = (m.get("content") or "")[:120]
            console.print(f"  [{ts}] [cyan]{fr}[/cyan] → {to} ({mtype}): {content}")

    _output(data, _human)


@inbox_app.command("watch")
def inbox_watch(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    poll_interval: float = typer.Option(1.0, "--poll-interval", "-p", help="Poll interval in seconds"),
    exec_cmd: Optional[str] = typer.Option(None, "--exec", "-e", help="Shell command to run for each new message (msg data in env vars)"),
):
    """Watch inbox for new messages (blocking, Ctrl+C to stop).

    With --exec, runs a shell command for each message. Message data is passed
    via env vars: CLAWTEAM_MSG_FROM, CLAWTEAM_MSG_TO, CLAWTEAM_MSG_CONTENT,
    CLAWTEAM_MSG_TYPE, CLAWTEAM_MSG_TIMESTAMP, CLAWTEAM_MSG_JSON.
    """
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.watcher import InboxWatcher

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)

    if not _json_output:
        console.print(f"Watching inbox for '{agent_name}' in team '{team}'... (Ctrl+C to stop)")
        if exec_cmd:
            console.print(f"  exec: {exec_cmd}")

    watcher = InboxWatcher(
        team_name=team,
        agent_name=agent_name,
        mailbox=mailbox,
        poll_interval=poll_interval,
        json_output=_json_output,
        exec_cmd=exec_cmd,
    )
    watcher.watch()


# ============================================================================
# Runtime Commands
# ============================================================================

runtime_app = typer.Typer(help="Tmux-only runtime routing and live injection")
app.add_typer(runtime_app, name="runtime")


@runtime_app.command("inject")
def runtime_inject(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Target agent name"),
    source: str = typer.Option("system", "--source", "-s", help="Runtime notification source"),
    channel: str = typer.Option("direct", "--channel", help="Runtime notification channel"),
    priority: str = typer.Option("medium", "--priority", help="Runtime notification priority"),
    summary: str = typer.Option(..., "--summary", help="Summary text for the injected notification"),
    evidence: list[str] = typer.Option([], "--evidence", "-e", help="Repeatable evidence line"),
    recommended_next_action: Optional[str] = typer.Option(
        None,
        "--recommended-next-action",
        help="Optional recommended next action",
    ),
):
    """Inject a structured runtime notification into a running tmux agent."""
    from clawteam.spawn.tmux_backend import TmuxBackend
    from clawteam.team.routing_policy import RuntimeEnvelope

    envelope = RuntimeEnvelope(
        source=source,
        target=agent,
        channel=channel,
        priority=priority,
        message_type="manual",
        summary=summary,
        evidence=list(evidence),
        recommended_next_action=recommended_next_action,
    )
    ok, status = TmuxBackend().inject_runtime_message(team, agent, envelope)
    if not ok:
        console.print(f"[red]{status}[/red]")
        raise typer.Exit(1)

    _output(
        {"team": team, "agent": agent, "status": status},
        lambda data: console.print(f"[green]OK[/green] {data['status']}"),
    )


@runtime_app.command("watch")
def runtime_watch(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    poll_interval: float = typer.Option(1.0, "--poll-interval", "-p", help="Poll interval in seconds"),
    exec_cmd: Optional[str] = typer.Option(
        None,
        "--exec",
        "-e",
        help="Shell command to run for each new message (msg data in env vars)",
    ),
):
    """Watch an inbox and route new messages into the running tmux session."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.router import RuntimeRouter
    from clawteam.team.watcher import InboxWatcher

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)
    router = RuntimeRouter(
        team_name=team,
        agent_name=agent_name,
        session_agent_name=agent or identity.agent_name,
    )

    if not _json_output:
        console.print(
            f"Watching runtime routes for '{agent_name}' in team '{team}'... (Ctrl+C to stop)"
        )
        if exec_cmd:
            console.print(f"  exec: {exec_cmd}")

    watcher = InboxWatcher(
        team_name=team,
        agent_name=agent_name,
        mailbox=mailbox,
        poll_interval=poll_interval,
        json_output=_json_output,
        exec_cmd=exec_cmd,
        runtime_router=router,
    )
    watcher.watch()


@runtime_app.command("state")
def runtime_state(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show persisted Phase 1 runtime throttle and dispatch state."""
    from clawteam.team.routing_policy import DefaultRoutingPolicy

    state = DefaultRoutingPolicy(team_name=team).read_state()

    def _human(data):
        console.print(
            f"Runtime state for '{data['team']}' (throttle={data['throttleSeconds']}s)"
        )
        routes = data.get("routes", {})
        if not routes:
            console.print("[dim]No runtime route state.[/dim]")
            return
        for key in sorted(routes):
            route = routes[key]
            console.print(
                f"  {route.get('source', '?')} -> {route.get('target', '?')} "
                f"pending={route.get('pendingCount', 0)} "
                f"status={route.get('lastDispatchStatus', 'idle')} "
                f"flushAfter={route.get('flushAfter', '') or '-'}"
            )

    _output(state, _human)


# ============================================================================
# Task Commands
# ============================================================================

task_app = typer.Typer(help="Task management commands")
app.add_typer(task_app, name="task")


@task_app.command("create")
def task_create(
    team: str = typer.Argument(..., help="Team name"),
    subject: str = typer.Argument(..., help="Task subject"),
    description: str = typer.Option("", "--description", "-d", help="Task description"),
    owner: Optional[str] = typer.Option(None, "--owner", "--agent", "-o", "-a", help="Owner agent name"),
    priority: str = typer.Option("medium", "--priority", "-p", help="Task priority: low, medium, high, urgent"),
    blocks: Optional[str] = typer.Option(None, "--blocks", help="Comma-separated task IDs this blocks"),
    blocked_by: Optional[str] = typer.Option(None, "--blocked-by", help="Comma-separated task IDs this is blocked by"),
):
    """Create a new task (TaskCreate)."""
    from clawteam.team.models import TaskPriority
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    blocks_list = [b.strip() for b in blocks.split(",") if b.strip()] if blocks else []
    blocked_by_list = [b.strip() for b in blocked_by.split(",") if b.strip()] if blocked_by else []

    try:
        task = store.create(
            subject=subject,
            description=description,
            owner=owner or "",
            priority=TaskPriority(priority),
            blocks=blocks_list,
            blocked_by=blocked_by_list,
        )
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = _dump(task)
    _output(data, lambda d: (
        console.print(f"[green]OK[/green] Task created: {d['id']}"),
        console.print(f"  Subject: {d['subject']}"),
        console.print(f"  Status: {d['status']}"),
        console.print(f"  Priority: {d.get('priority', 'medium')}"),
        console.print(f"  Owner: {d.get('owner', '')}") if d.get('owner') else None,
    ))


@task_app.command("get")
def task_get(
    team: str = typer.Argument(..., help="Team name"),
    task_id: str = typer.Argument(..., help="Task ID"),
):
    """Get a single task (TaskGet)."""
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    task = store.get(task_id)
    if not task:
        _output({"error": f"Task '{task_id}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = _dump(task)

    def _human(d):
        console.print(f"Task: [cyan]{d['id']}[/cyan]")
        console.print(f"  Subject: {d['subject']}")
        console.print(f"  Status: {d['status']}")
        console.print(f"  Priority: {d.get('priority', 'medium')}")
        if d.get('owner'):
            console.print(f"  Owner: {d['owner']}")
        if d.get('lockedBy'):
            console.print(f"  Locked by: [yellow]{d['lockedBy']}[/yellow] (since {format_timestamp(d.get('lockedAt', ''))})")
        if d.get('description'):
            console.print(f"  Description: {d['description']}")
        if d.get('blocks'):
            console.print(f"  Blocks: {', '.join(d['blocks'])}")
        if d.get('blockedBy'):
            console.print(f"  Blocked by: {', '.join(d['blockedBy'])}")

    _output(data, _human)


@task_app.command("update")
def task_update(
    team: str = typer.Argument(..., help="Team name"),
    task_id: str = typer.Argument(..., help="Task ID"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="New status: pending, in_progress, completed, blocked"),
    owner: Optional[str] = typer.Option(None, "--owner", "--agent", "-o", "-a", help="New owner"),
    subject: Optional[str] = typer.Option(None, "--subject", help="New subject"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description"),
    priority: Optional[str] = typer.Option(None, "--priority", "-p", help="New priority: low, medium, high, urgent"),
    add_blocks: Optional[str] = typer.Option(None, "--add-blocks", help="Comma-separated task IDs this blocks"),
    add_blocked_by: Optional[str] = typer.Option(None, "--add-blocked-by", help="Comma-separated task IDs blocking this"),
    force: bool = typer.Option(False, "--force", "-f", help="Force override task lock"),
):
    """Update a task (TaskUpdate)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.models import TaskPriority, TaskStatus
    from clawteam.team.tasks import TaskLockError, TaskStore

    store = TaskStore(team)
    ts = TaskStatus(status) if status else None
    tp = TaskPriority(priority) if priority else None
    blocks_list = [b.strip() for b in add_blocks.split(",") if b.strip()] if add_blocks else None
    blocked_by_list = [b.strip() for b in add_blocked_by.split(",") if b.strip()] if add_blocked_by else None

    caller = AgentIdentity.from_env().agent_name

    try:
        task = store.update(
            task_id,
            status=ts,
            owner=owner,
            subject=subject,
            description=description,
            priority=tp,
            add_blocks=blocks_list,
            add_blocked_by=blocked_by_list,
            caller=caller,
            force=force,
        )
    except TaskLockError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]Lock conflict: {d['error']}[/red]"))
        raise typer.Exit(1)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    if not task:
        _output({"error": f"Task '{task_id}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = _dump(task)
    _output(data, lambda d: console.print(f"[green]OK[/green] Task {d['id']} updated"))


@task_app.command("list")
def task_list(
    team: str = typer.Argument(..., help="Team name"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    owner: Optional[str] = typer.Option(None, "--owner", "--agent", "-o", "-a", help="Filter by owner"),
    priority: Optional[str] = typer.Option(None, "--priority", "-p", help="Filter by priority: low, medium, high, urgent"),
    sort_priority: bool = typer.Option(False, "--sort-priority", help="Sort by priority (urgent first)"),
):
    """List tasks for a team (TaskList)."""
    from clawteam.team.models import TaskPriority, TaskStatus
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    ts = TaskStatus(status) if status else None
    tp = TaskPriority(priority) if priority else None
    tasks = store.list_tasks(status=ts, owner=owner, priority=tp, sort_by_priority=sort_priority)

    data = [_dump(t) for t in tasks]

    def _human(items):
        if not items:
            console.print("[dim]No tasks found[/dim]")
            return
        table = Table(title=f"Tasks - {team}")
        table.add_column("ID", style="dim")
        table.add_column("Subject", style="cyan")
        table.add_column("Status")
        table.add_column("Priority")
        table.add_column("Owner")
        table.add_column("Lock", style="yellow")
        table.add_column("Blocked By", style="dim")
        for t in items:
            st = t.get("status", "")
            style = {"pending": "white", "in_progress": "yellow", "completed": "green", "blocked": "red"}.get(st, "")
            priority_value = t.get("priority", "medium")
            priority_style = {
                "urgent": "red bold",
                "high": "yellow",
                "medium": "white",
                "low": "dim",
            }.get(priority_value, "")
            table.add_row(
                t["id"],
                t["subject"],
                f"[{style}]{st}[/{style}]" if style else st,
                f"[{priority_style}]{priority_value}[/{priority_style}]" if priority_style else priority_value,
                t.get("owner") or "",
                t.get("lockedBy") or "",
                ", ".join(t.get("blockedBy", [])),
            )
        console.print(table)

    _output(data, _human)


@task_app.command("stats")
def task_stats(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show task timing statistics for a team."""
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    stats = store.get_stats()

    def _human(d):
        table = Table(title=f"Task Stats - {team}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Total tasks", str(d["total"]))
        table.add_row("Completed", str(d["completed"]))
        table.add_row("In progress", str(d["in_progress"]))
        table.add_row("Pending", str(d["pending"]))
        table.add_row("Blocked", str(d["blocked"]))
        table.add_row("With timing data", str(d["timed_completed"]))
        avg = d["avg_duration_seconds"]
        if avg > 0:
            # Show in a readable format
            if avg < 60:
                table.add_row("Avg completion time", f"{avg:.1f}s")
            elif avg < 3600:
                table.add_row("Avg completion time", f"{avg / 60:.1f}m")
            else:
                table.add_row("Avg completion time", f"{avg / 3600:.1f}h")
        else:
            table.add_row("Avg completion time", "-")
        console.print(table)

    _output(stats, _human)


# ============================================================================
# Cost Commands
# ============================================================================

cost_app = typer.Typer(help="Cost tracking and budget management")
app.add_typer(cost_app, name="cost")


@cost_app.command("report")
def cost_report(
    team: str = typer.Argument(..., help="Team name"),
    input_tokens: int = typer.Option(0, "--input-tokens", help="Input tokens consumed"),
    output_tokens: int = typer.Option(0, "--output-tokens", help="Output tokens consumed"),
    cost_cents: float = typer.Option(0.0, "--cost-cents", help="Cost in cents"),
    provider: str = typer.Option("", "--provider", help="Provider name (e.g. anthropic)"),
    model: str = typer.Option("", "--model", help="Model name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
):
    """Report token usage and cost for an agent."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.costs import CostStore
    from clawteam.team.manager import TeamManager

    agent_name = agent or AgentIdentity.from_env().agent_name
    store = CostStore(team)
    event = store.report(
        agent_name=agent_name,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_cents=cost_cents,
    )
    data = _dump(event)

    def _human(d):
        console.print(f"[green]OK[/green] Cost reported: ${d.get('costCents', 0) / 100:.4f}")

    _output(data, _human)

    # Check budget
    config = TeamManager.get_team(team)
    if config and config.budget_cents > 0:
        summary = store.summary()
        if summary.total_cost_cents > config.budget_cents:
            budget_dollars = config.budget_cents / 100
            spent_dollars = summary.total_cost_cents / 100
            if not _json_output:
                console.print(
                    f"[yellow]WARNING: Budget exceeded! "
                    f"Spent ${spent_dollars:.2f} / ${budget_dollars:.2f}[/yellow]"
                )


@cost_app.command("show")
def cost_show(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by agent"),
):
    """Show cost summary and event history."""
    from clawteam.team.costs import CostStore
    from clawteam.team.manager import TeamManager

    store = CostStore(team)
    summary = store.summary()
    events = store.list_events(agent_name=agent or "")
    config = TeamManager.get_team(team)
    budget = config.budget_cents if config else 0.0

    data = {
        "summary": _dump(summary),
        "budget_cents": budget,
        "events": [_dump(e) for e in events],
    }

    def _human(d):
        s = d["summary"]
        total = s.get("totalCostCents", 0)
        console.print(f"\nCost Summary — [cyan]{team}[/cyan]")
        if budget > 0:
            console.print(f"  Total: ${total / 100:.4f} / ${budget / 100:.2f}")
        else:
            console.print(f"  Total: ${total / 100:.4f}")
        console.print(f"  Input tokens:  {s.get('totalInputTokens', 0):,}")
        console.print(f"  Output tokens: {s.get('totalOutputTokens', 0):,}")
        console.print(f"  Events: {s.get('eventCount', 0)}")
        by_agent = s.get("byAgent", {})
        if by_agent:
            console.print("  By agent:")
            for a, c in sorted(by_agent.items()):
                console.print(f"    {a}: ${c / 100:.4f}")

        evts = d["events"]
        if evts:
            table = Table(title="Recent Events")
            table.add_column("Time", style="dim")
            table.add_column("Agent", style="cyan")
            table.add_column("In Tokens", justify="right")
            table.add_column("Out Tokens", justify="right")
            table.add_column("Cost", justify="right")
            table.add_column("Model", style="dim")
            for e in evts[-20:]:  # show last 20
                table.add_row(
                    format_timestamp(e.get("reportedAt")),
                    e.get("agentName", ""),
                    f"{e.get('inputTokens', 0):,}",
                    f"{e.get('outputTokens', 0):,}",
                    f"${e.get('costCents', 0) / 100:.4f}",
                    e.get("model", ""),
                )
            console.print(table)

    _output(data, _human)


@cost_app.command("budget")
def cost_budget(
    team: str = typer.Argument(..., help="Team name"),
    dollars: float = typer.Argument(..., help="Budget in dollars (0 = unlimited)"),
):
    """Set team budget in dollars."""
    from clawteam.team.manager import TeamManager

    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    config.budget_cents = dollars * 100
    # Save config back
    from clawteam.team.manager import _save_config
    _save_config(config)

    _output(
        {"status": "set", "team": team, "budgetDollars": dollars},
        lambda d: console.print(
            f"[green]OK[/green] Budget set to ${dollars:.2f}" if dollars > 0
            else "[green]OK[/green] Budget removed (unlimited)"
        ),
    )


@task_app.command("wait")
def task_wait(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent inbox to monitor (default: leader from team config)"),
    poll_interval: float = typer.Option(5.0, "--poll-interval", "-p", help="Seconds between polls"),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Max seconds to wait (default: no limit)"),
):
    """Block until all tasks in a team are completed."""
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.tasks import TaskStore
    from clawteam.team.waiter import TaskWaiter

    # Resolve agent name for inbox monitoring
    agent_name = agent
    if not agent_name:
        agent_name = TeamManager.get_leader_inbox(team)
    if not agent_name:
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity.from_env()
        agent_name = TeamManager.resolve_inbox(team, identity.agent_name, identity.user)
    elif agent:
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity.from_env()
        agent_name = TeamManager.resolve_inbox(team, agent_name, identity.user)

    mailbox = MailboxManager(team)
    store = TaskStore(team)

    def _on_message(msg):
        ts = msg.timestamp
        if ts and "T" in ts:
            ts = ts.split("T")[1][:8]
        from_agent = msg.from_agent or "?"
        content = msg.content or ""
        if _json_output:
            print(json.dumps({
                "event": "message",
                "from": from_agent,
                "content": content,
                "timestamp": msg.timestamp,
            }), flush=True)
        else:
            console.print(f"  {ts}  message from={from_agent}: {content}")

    last_progress = ""

    def _on_progress(completed, total, in_progress, pending, blocked):
        nonlocal last_progress
        summary = f"{completed}/{total}"
        if summary == last_progress:
            return
        last_progress = summary
        if _json_output:
            print(json.dumps({
                "event": "progress",
                "completed": completed,
                "total": total,
                "in_progress": in_progress,
                "pending": pending,
                "blocked": blocked,
            }), flush=True)
        else:
            console.print(
                f"  {completed}/{total} tasks completed"
                f"  ({in_progress} in progress, {pending} pending, {blocked} blocked)"
            )

    if not _json_output:
        timeout_str = f"{timeout:.0f}s" if timeout else "none"
        console.print(f"Waiting for all tasks in team '[cyan]{team}[/cyan]' to complete...")
        console.print(
            f"  Agent inbox: {agent_name}  |  Poll interval: {poll_interval}s  |  Timeout: {timeout_str}"
        )
        console.print()

    def _on_agent_dead(dead_agent, abandoned_tasks):
        task_subjects = ", ".join(t.subject for t in abandoned_tasks)
        if _json_output:
            print(json.dumps({
                "event": "agent_dead",
                "agent": dead_agent,
                "abandoned_tasks": [{"id": t.id, "subject": t.subject} for t in abandoned_tasks],
            }), flush=True)
        else:
            console.print(
                f"  [yellow]Agent '{dead_agent}' is dead.[/yellow]"
                f" Reset {len(abandoned_tasks)} task(s) to pending: {task_subjects}"
            )

    waiter = TaskWaiter(
        team_name=team,
        agent_name=agent_name,
        mailbox=mailbox,
        task_store=store,
        poll_interval=poll_interval,
        timeout=timeout,
        on_message=_on_message,
        on_progress=_on_progress,
        on_agent_dead=_on_agent_dead,
    )
    result = waiter.wait()

    if _json_output:
        print(json.dumps({
            "event": "result",
            "status": result.status,
            "elapsed": round(result.elapsed, 1),
            "total": result.total,
            "completed": result.completed,
            "in_progress": result.in_progress,
            "pending": result.pending,
            "blocked": result.blocked,
            "messages_received": result.messages_received,
            "task_details": result.task_details,
        }), flush=True)
    else:
        console.print()
        if result.status == "completed":
            console.print(
                f"[green]All {result.total} tasks completed![/green]"
                f" ({result.elapsed:.1f}s, {result.messages_received} messages)"
            )
        elif result.status == "timeout":
            console.print(
                f"[yellow]Timeout[/yellow] after {result.elapsed:.1f}s."
                f" {result.completed}/{result.total} completed."
            )
            _print_incomplete_tasks(result.task_details)
        else:
            console.print(
                f"[yellow]Interrupted[/yellow] after {result.elapsed:.1f}s."
                f" {result.completed}/{result.total} completed."
            )
            _print_incomplete_tasks(result.task_details)

    if result.status != "completed":
        raise typer.Exit(1)


def _print_incomplete_tasks(task_details: list[dict]):
    """Print tasks that are not completed."""
    incomplete = [t for t in task_details if t["status"] != "completed"]
    if incomplete:
        console.print("  Incomplete tasks:")
        for t in incomplete:
            console.print(f"    [{t['status']}] {t['id']}  {t['subject']}  (owner: {t['owner'] or '-'})")


# ============================================================================
# Session Commands
# ============================================================================

session_app = typer.Typer(help="Session persistence for agent resume")
app.add_typer(session_app, name="session")


@session_app.command("save")
def session_save(
    team: str = typer.Argument(..., help="Team name"),
    session_id: str = typer.Option("", "--session-id", "-s", help="Claude Code session ID"),
    last_task: str = typer.Option("", "--last-task", help="Last task ID worked on"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
):
    """Save agent session for later resume."""
    from clawteam.identity import AgentIdentity
    from clawteam.spawn.sessions import SessionStore

    agent_name = agent or AgentIdentity.from_env().agent_name
    store = SessionStore(team)
    session = store.save(
        agent_name=agent_name,
        session_id=session_id,
        last_task_id=last_task,
    )
    data = _dump(session)
    _output(data, lambda d: console.print(f"[green]OK[/green] Session saved for '{agent_name}'"))


@session_app.command("show")
def session_show(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by agent"),
):
    """Show saved sessions."""
    from clawteam.spawn.sessions import SessionStore

    store = SessionStore(team)
    if agent:
        session = store.load(agent)
        if not session:
            _output({"error": f"No session for '{agent}'"}, lambda d: console.print(f"[dim]{d['error']}[/dim]"))
            return
        data = _dump(session)
        _output(data, lambda d: (
            console.print(f"Session: [cyan]{d.get('agentName', '')}[/cyan]"),
            console.print(f"  Session ID: {d.get('sessionId', '')}"),
            console.print(f"  Last task:  {d.get('lastTaskId', '')}"),
            console.print(f"  Saved at:   {format_timestamp(d.get('savedAt', ''))}"),
        ))
    else:
        sessions = store.list_sessions()
        data = [_dump(s) for s in sessions]

        def _human(items):
            if not items:
                console.print("[dim]No saved sessions[/dim]")
                return
            table = Table(title=f"Sessions — {team}")
            table.add_column("Agent", style="cyan")
            table.add_column("Session ID")
            table.add_column("Last Task", style="dim")
            table.add_column("Saved At", style="dim")
            for s in items:
                table.add_row(
                    s.get("agentName", ""),
                    s.get("sessionId", ""),
                    s.get("lastTaskId", ""),
                    format_timestamp(s.get("savedAt")),
                )
            console.print(table)

        _output(data, _human)


@session_app.command("clear")
def session_clear(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: all)"),
):
    """Clear saved sessions."""
    from clawteam.spawn.sessions import SessionStore

    store = SessionStore(team)
    if agent:
        if store.clear(agent):
            _output({"status": "cleared", "agent": agent}, lambda d: console.print(f"[green]OK[/green] Session cleared for '{agent}'"))
        else:
            _output({"status": "not_found", "agent": agent}, lambda d: console.print(f"[dim]No session for '{agent}'[/dim]"))
    else:
        sessions = store.list_sessions()
        count = 0
        for s in sessions:
            if store.clear(s.agent_name):
                count += 1
        _output({"status": "cleared", "count": count}, lambda d: console.print(f"[green]OK[/green] Cleared {count} session(s)"))


# ============================================================================
# Plan Commands
# ============================================================================

plan_app = typer.Typer(help="Plan management commands")
app.add_typer(plan_app, name="plan")


@plan_app.command("submit")
def plan_submit(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name submitting the plan"),
    plan: str = typer.Argument(..., help="Plan content or path to a file"),
    summary: str = typer.Option("", "--summary", "-s", help="Brief plan summary"),
):
    """Submit a plan for leader approval (triggers plan_approval_request)."""
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.plan import PlanManager

    plan_content = plan
    p = Path(plan)
    if p.exists() and p.is_file():
        plan_content = p.read_text(encoding="utf-8")

    leader_name = TeamManager.get_leader_name(team)
    if not leader_name:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    plan_id = pm.submit_plan(agent_name=agent, leader_name=leader_name, plan_content=plan_content, summary=summary)

    _output(
        {"status": "submitted", "planId": plan_id, "agent": agent},
        lambda d: console.print(f"[green]OK[/green] Plan {d['planId']} submitted by {d['agent']}"),
    )


@plan_app.command("approve")
def plan_approve(
    team: str = typer.Argument(..., help="Team name"),
    plan_id: str = typer.Argument(..., help="Plan ID (requestId from plan_approval_request)"),
    agent: str = typer.Argument(..., help="Agent who submitted the plan (target_agent_id)"),
    feedback: str = typer.Option("", "--feedback", "-f", help="Optional feedback"),
):
    """Approve a submitted plan (approvePlan)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.plan import PlanManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    pm.approve_plan(leader_name=identity.agent_name, plan_id=plan_id, agent_name=agent, feedback=feedback)

    _output(
        {"status": "approved", "planId": plan_id},
        lambda d: console.print(f"[green]OK[/green] Plan {plan_id} approved"),
    )


@plan_app.command("reject")
def plan_reject(
    team: str = typer.Argument(..., help="Team name"),
    plan_id: str = typer.Argument(..., help="Plan ID (requestId from plan_approval_request)"),
    agent: str = typer.Argument(..., help="Agent who submitted the plan (target_agent_id)"),
    feedback: str = typer.Option("", "--feedback", "-f", help="Rejection feedback"),
):
    """Reject a submitted plan (rejectPlan)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.plan import PlanManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    pm.reject_plan(leader_name=identity.agent_name, plan_id=plan_id, agent_name=agent, feedback=feedback)

    _output(
        {"status": "rejected", "planId": plan_id},
        lambda d: console.print(f"[green]OK[/green] Plan {plan_id} rejected"),
    )


# ============================================================================
# Lifecycle Commands
# ============================================================================

lifecycle_app = typer.Typer(help="Agent lifecycle commands (shutdown protocol)")
app.add_typer(lifecycle_app, name="lifecycle")


@lifecycle_app.command("request-shutdown")
def lifecycle_request_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    from_agent: str = typer.Argument(..., help="Requesting agent name"),
    to_agent: str = typer.Argument(..., help="Target agent name"),
    reason: str = typer.Option("", "--reason", "-r", help="Shutdown reason"),
):
    """Request an agent to shut down (requestShutdown)."""
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    request_id = lm.request_shutdown(from_agent=from_agent, to_agent=to_agent, reason=reason)

    _output(
        {"status": "requested", "requestId": request_id, "from": from_agent, "to": to_agent},
        lambda d: console.print(f"[green]OK[/green] Shutdown request sent to '{to_agent}' (id: {request_id})"),
    )


@lifecycle_app.command("approve-shutdown")
def lifecycle_approve_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Shutdown request ID"),
    agent: str = typer.Argument(..., help="Agent approving shutdown (self)"),
):
    """Approve a shutdown request (approveShutdown). Agent agrees to shut down."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    leader_name = identity.agent_name
    lm.approve_shutdown(agent_name=agent, request_id=request_id, requester_name=leader_name)

    _output(
        {"status": "approved", "requestId": request_id, "agent": agent},
        lambda d: console.print(f"[green]OK[/green] {agent} approved shutdown"),
    )


@lifecycle_app.command("reject-shutdown")
def lifecycle_reject_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Shutdown request ID"),
    agent: str = typer.Argument(..., help="Agent rejecting shutdown"),
    reason: str = typer.Option("", "--reason", "-r", help="Rejection reason"),
):
    """Reject a shutdown request (rejectShutdown)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    lm.reject_shutdown(agent_name=agent, request_id=request_id, requester_name=identity.agent_name, reason=reason)

    _output(
        {"status": "rejected", "requestId": request_id, "agent": agent, "reason": reason},
        lambda d: console.print(f"[green]OK[/green] {agent} rejected shutdown"),
    )


@lifecycle_app.command("idle")
def lifecycle_idle(
    team: str = typer.Argument(..., help="Team name"),
    last_task: Optional[str] = typer.Option(None, "--last-task", help="Last task ID worked on"),
    task_status: Optional[str] = typer.Option(None, "--task-status", help="Status of last task"),
):
    """Send idle notification to leader."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    team_name = team
    leader_name = TeamManager.get_leader_name(team_name)
    if not leader_name:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team_name)
    lm = LifecycleManager(team_name, mailbox)
    lm.send_idle(
        agent_name=identity.agent_name,
        agent_id=identity.agent_id,
        leader_name=leader_name,
        last_task=last_task or "",
        task_status=task_status or "",
    )

    _output(
        {"status": "idle_sent", "agent": identity.agent_name, "leader": leader_name},
        lambda d: console.print(f"[green]OK[/green] Idle notification sent to '{leader_name}'"),
    )


@lifecycle_app.command("on-exit")
def lifecycle_on_exit(
    team: str = typer.Option(..., "--team", "-t", help="Team name"),
    agent: str = typer.Option(..., "--agent", "-n", help="Agent name"),
):
    """Handle agent process exit: clean up session and reset in_progress tasks.

    This is called automatically as a post-exit hook when an agent process terminates.
    """
    from clawteam.spawn.sessions import SessionStore
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import TaskStatus
    from clawteam.team.tasks import TaskStore

    # Always clean up the agent's session file, regardless of task status.
    # Without this, session files accumulate indefinitely under
    # ~/.clawteam/sessions/{team}/ after every agent exit.
    SessionStore(team).clear(agent)

    store = TaskStore(team)
    tasks = store.list_tasks()

    # Find this agent's in_progress tasks and reset them
    abandoned = [
        t for t in tasks
        if t.owner == agent and t.status == TaskStatus.in_progress
    ]

    if not abandoned:
        return

    for t in abandoned:
        store.update(t.id, status=TaskStatus.pending)

    # Notify leader
    leader_name = TeamManager.get_leader_name(team)
    if leader_name:
        mailbox = MailboxManager(team)
        task_subjects = ", ".join(t.subject for t in abandoned)
        mailbox.send(
            from_agent=agent,
            to=leader_name,
            content=f"Agent '{agent}' exited unexpectedly. "
                    f"Reset {len(abandoned)} task(s) to pending: {task_subjects}",
        )

    _output(
        {
            "status": "agent_exited",
            "agent": agent,
            "abandoned_tasks": [{"id": t.id, "subject": t.subject} for t in abandoned],
        },
        lambda d: console.print(
            f"[yellow]Agent '{agent}' exited.[/yellow] "
            f"Reset {len(d['abandoned_tasks'])} task(s) to pending."
        ),
    )


@lifecycle_app.command("check-zombies")
def lifecycle_check_zombies(
    team: str = typer.Option(..., "--team", "-t", help="Team name"),
    max_hours: float = typer.Option(2.0, "--max-hours", help="Warn if agent has been running longer than this many hours"),
):
    """Warn about agents that have been running unusually long (possible zombies).

    Agents that never called on-exit will accumulate as background processes.
    This command helps identify them so you can decide whether to stop them manually.
    """
    from clawteam.spawn.registry import list_zombie_agents

    zombies = list_zombie_agents(team, max_hours=max_hours)

    if not zombies:
        _output(
            {"team": team, "zombies": []},
            lambda d: console.print(f"[green]✓[/green] No zombie agents detected for team '{team}'"),
        )
        return

    def _fmt(d: dict) -> None:
        console.print(
            f"[bold yellow]⚠ {len(d['zombies'])} zombie agent(s) detected in team '{team}':[/bold yellow]"
        )
        for z in d["zombies"]:
            console.print(
                f"  [yellow]• {z['agent_name']}[/yellow]  "
                f"pid={z['pid']}  backend={z['backend']}  "
                f"running={z['running_hours']}h"
            )
        console.print(
            "\n[dim]These processes did not call lifecycle on-exit. "
            "Inspect them manually and terminate them with your process manager if they are truly stuck.[/dim]"
        )

    _output({"team": team, "zombies": zombies}, _fmt)
    raise typer.Exit(1)


# ============================================================================
# Spawn Command
# ============================================================================

@app.command("spawn")
def spawn_agent(
    backend: Optional[str] = typer.Argument(None, help="Backend: tmux (default) or subprocess"),
    command: list[str] = typer.Argument(None, help="Command and arguments to run (default: claude)"),
    team: Optional[str] = typer.Option(None, "--team", "-t", help="Team name"),
    agent_name: Optional[str] = typer.Option(None, "--agent-name", "-n", help="Agent name"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Apply a named runtime profile"),
    agent_type: str = typer.Option("general-purpose", "--agent-type", help="Agent type"),
    task: Optional[str] = typer.Option(None, "--task", help="Task to assign (becomes the agent's initial prompt)"),
    workspace: Optional[bool] = typer.Option(None, "--workspace/--no-workspace", "-w", help="Create isolated git worktree (default: auto)"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path (default: cwd)"),
    skip_permissions: Optional[bool] = typer.Option(None, "--skip-permissions/--no-skip-permissions", help="Skip tool approval for claude (default: from config, true)"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume previous session if available"),
    replace: bool = typer.Option(False, "--replace", help="Replace a running agent with the same name"),
    skill: Optional[list[str]] = typer.Option(None, "--skill", help="Skill name(s) to inject into the agent's system prompt (repeatable, claude only)"),
):
    """Spawn a new agent process with identity + task as its initial prompt.

    Defaults: tmux backend, claude command, git worktree isolation, skip-permissions on.

    Backends:
      tmux        - Launch in tmux windows (visual monitoring)
      subprocess  - Launch as background processes
    """
    from clawteam.config import get_effective
    from clawteam.spawn import get_backend
    from clawteam.spawn.profiles import apply_profile, load_profile, resolve_profile_name

    # Resolve defaults from config
    if backend is None:
        backend, _ = get_effective("default_backend")
        backend = backend or "tmux"
    try:
        profile = resolve_profile_name(profile, command=list(command or []))
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    _team = team or "default"
    _name = agent_name or f"agent-{uuid.uuid4().hex[:6]}"
    _id = uuid.uuid4().hex[:12]
    user_name = os.environ.get("CLAWTEAM_USER", "")

    from clawteam.spawn.registry import is_agent_alive, stop_agent

    existing_alive = is_agent_alive(_team, _name)
    if existing_alive is True:
        if not replace:
            _output(
                {
                    "error": (
                        f"Agent '{_name}' is already running in team '{_team}'. "
                        "Use --replace to stop it and spawn a new instance."
                    )
                },
                lambda d: console.print(f"[red]{d['error']}[/red]"),
            )
            raise typer.Exit(1)

        if stop_agent(_team, _name) is not True:
            _output(
                {
                    "error": (
                        f"Failed to stop running agent '{_name}' in team '{_team}'. "
                        "Retry after the existing process exits."
                    )
                },
                lambda d: console.print(f"[red]{d['error']}[/red]"),
            )
            raise typer.Exit(1)

    # Resolve skip_permissions from config
    if skip_permissions is None:
        sp_val, _ = get_effective("skip_permissions")
        skip_permissions = str(sp_val).lower() not in ("false", "0", "no", "")

    try:
        be = get_backend(backend)
    except ValueError as e:
        message = str(e) + _spawn_backend_hint(backend, team)
        _output({"error": message}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    # Workspace: resolve from flag or config (default: auto)
    cwd = None
    ws_branch = ""
    ws_mode = ""
    ws_mgr = None
    if workspace is None:
        ws_mode, _ = get_effective("workspace")
        ws_mode = ws_mode or "auto"
        workspace = ws_mode in ("auto", "always")
    elif workspace is False:
        ws_mode = "never"

    if workspace:
        from clawteam.workspace import get_workspace_manager
        ws_mgr = get_workspace_manager(repo)
        if ws_mgr is None:
            if ws_mode not in ("auto", ""):
                console.print("[red]Not in a git repository. Use --repo or cd into a repo.[/red]")
                raise typer.Exit(1)
        else:
            ws_info = ws_mgr.create_workspace(team_name=_team, agent_name=_name, agent_id=_id)
            cwd = ws_info.worktree_path
            ws_branch = ws_info.branch_name
            console.print(f"[dim]Workspace: {cwd} (branch: {ws_branch})[/dim]")
    elif repo:
        import os as _os_repo
        cwd = _os_repo.path.abspath(repo)

    profile_env: dict[str, str] = {}
    if profile:
        try:
            resolved_profile = load_profile(profile)
            command, profile_env, _ = apply_profile(
                resolved_profile,
                command=list(command or []),
            )
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    elif not command:
        command = ["claude"]

    # Auto-register agent as team member
    from clawteam.team.manager import TeamManager
    team_created = False
    member_added = False
    if TeamManager.get_team(_team) is None:
        TeamManager.create_team(
            name=_team,
            leader_name=_name,
            leader_id=_id,
            description="Auto-created by clawteam spawn",
            user=user_name,
            leader_agent_type=agent_type,
        )
        team_created = True
        member_added = True
    try:
        if not team_created:
            TeamManager.add_member(
                team_name=_team,
                member_name=_name,
                agent_id=_id,
                agent_type=agent_type,
                user=user_name,
            )
            member_added = True
    except ValueError:
        pass  # already a member, ignore

    # Build prompt: identity + task + clawteam coordination guide
    prompt = None
    if task:
        from clawteam.spawn.prompt import build_agent_prompt

        leader_name = TeamManager.get_leader_name(_team) or "leader"
        prompt = build_agent_prompt(
            agent_name=_name,
            agent_id=_id,
            agent_type=agent_type,
            team_name=_team,
            leader_name=leader_name,
            task=task,
            user=user_name,
            workspace_dir=cwd or "",
            workspace_branch=ws_branch,
            isolated_workspace=bool(workspace and cwd),
            repo_path=repo,
        )

    # Session resume: inject --resume flag for claude commands
    if resume:
        from clawteam.spawn.sessions import SessionStore
        session_store = SessionStore(_team)
        session = session_store.load(_name)
        if session and session.session_id:
            # Add --resume to claude command
            if command and Path(command[0]).name in ("claude", "claude-code"):
                command = list(command) + ["--resume", session.session_id]
                console.print(f"[dim]Resuming session: {session.session_id}[/dim]")
            if prompt:
                prompt += "\nYou are resuming a previous session."

    system_prompt = None
    if skill:
        skill_parts: list[str] = []
        for skill_name in skill:
            content = _load_skill_content(skill_name)
            if content is None:
                console.print(
                    f"[yellow]Warning: skill '{skill_name}' not found in ~/.claude/skills/[/yellow]"
                )
                continue
            skill_parts.append(content)
        if skill_parts:
            system_prompt = "\n\n".join(skill_parts)

    result = be.spawn(
        command=command,
        agent_name=_name,
        agent_id=_id,
        agent_type=agent_type,
        team_name=_team,
        prompt=prompt,
        env=profile_env or None,
        cwd=cwd,
        skip_permissions=skip_permissions,
        system_prompt=system_prompt,
    )

    if result.startswith("Error"):
        if member_added:
            if team_created:
                TeamManager.cleanup(_team)
            else:
                TeamManager.remove_member(_team, _name)
        if ws_mgr is not None and cwd:
            try:
                ws_mgr.cleanup_workspace(_team, _name, auto_checkpoint=False)
            except Exception:
                pass
        _output({"error": result}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    _output(
        {"status": "spawned", "backend": backend, "agentName": _name, "agentId": _id, "message": result},
        lambda d: console.print(f"[green]OK[/green] {d['message']}"),
    )


# ============================================================================
# Identity Commands
# ============================================================================

identity_app = typer.Typer(help="Agent identity commands")
app.add_typer(identity_app, name="identity")


@identity_app.command("show")
def identity_show():
    """Show current agent identity (from environment variables)."""
    from clawteam.identity import AgentIdentity

    identity = AgentIdentity.from_env()
    data = {
        "agentId": identity.agent_id,
        "agentName": identity.agent_name,
        "user": identity.user,
        "agentType": identity.agent_type,
        "teamName": identity.team_name,
        "isLeader": identity.is_leader,
        "planModeRequired": identity.plan_mode_required,
    }

    def _human(d):
        console.print(f"Agent ID:   {d['agentId']}")
        console.print(f"Agent Name: {d['agentName']}")
        console.print(f"User:       {d['user'] or '(none)'}")
        console.print(f"Agent Type: {d['agentType']}")
        console.print(f"Team:       {d['teamName'] or '(none)'}")
        console.print(f"Is Leader:  {d['isLeader']}")
        console.print(f"Plan Mode:  {d['planModeRequired']}")

    _output(data, _human)


@identity_app.command("set")
def identity_set(
    agent_id: Optional[str] = typer.Option(None, "--agent-id", help="Agent ID"),
    agent_name: Optional[str] = typer.Option(None, "--agent-name", help="Agent name"),
    agent_type: Optional[str] = typer.Option(None, "--agent-type", help="Agent type"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name"),
):
    """Print shell export commands to set identity environment variables."""
    lines = []
    if agent_id:
        lines.append(f'export CLAWTEAM_AGENT_ID="{agent_id}"')
    if agent_name:
        lines.append(f'export CLAWTEAM_AGENT_NAME="{agent_name}"')
    if agent_type:
        lines.append(f'export CLAWTEAM_AGENT_TYPE="{agent_type}"')
    if team:
        lines.append(f'export CLAWTEAM_TEAM_NAME="{team}"')

    if not lines:
        console.print("[yellow]No options specified. Use --agent-id, --agent-name, --agent-type, --team[/yellow]")
        raise typer.Exit(1)

    output = "\n".join(lines)
    if _json_output:
        print(json.dumps({"exports": lines}))
    else:
        console.print("Run the following to set your identity:\n")
        console.print(output)
        console.print(f"\nOr use: eval $(clawteam identity set {' '.join(sys.argv[3:])})")


# ============================================================================
# Board Commands
# ============================================================================

board_app = typer.Typer(help="Team dashboard and kanban board.")
app.add_typer(board_app, name="board")


@board_app.command("show")
def board_show(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show detailed kanban board for a single team."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()
    try:
        data = collector.collect_team(team)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    _output(data, lambda d: BoardRenderer(console).render_team_board(d))


@board_app.command("update")
def board_update(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Compatibility alias; board state is team-wide"),
):
    """Compatibility alias: board state is derived from tasks and inbox messages."""
    from clawteam.board.collector import BoardCollector

    collector = BoardCollector()
    try:
        collector.collect_team(team)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    _output(
        {
            "status": "up_to_date",
            "team": team,
            "agent": agent,
            "note": "Board state is derived automatically from task and inbox updates.",
        },
        lambda d: console.print(
            "[green]OK[/green] Board state is already derived automatically from tasks and inbox messages. "
            "Use `clawteam task create/update` to change it, then `clawteam board show` or `board live` to refresh the view."
        ),
    )


@board_app.command("overview")
def board_overview():
    """Show overview of all teams."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()
    teams = collector.collect_overview()

    _output(teams, lambda d: BoardRenderer(console).render_overview(d))


@board_app.command("live")
def board_live(
    team: str = typer.Argument(..., help="Team name"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="Refresh interval in seconds"),
):
    """Live-refreshing kanban board. Ctrl+C to stop."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()

    # Validate team exists before starting live mode
    try:
        collector.collect_team(team)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    if not _json_output:
        console.print(f"Live board for '{team}' (interval: {interval}s). Ctrl+C to stop.")

    renderer = BoardRenderer(console)
    renderer.render_team_board_live(collector, team, interval=interval)


@board_app.command("serve")
def board_serve(
    team: Optional[str] = typer.Argument(None, help="Team name (optional, shows all if omitted)"),
    port: int = typer.Option(8080, "--port", "-p", help="HTTP server port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="SSE push interval in seconds"),
):
    """Start Web UI dashboard server."""
    from clawteam.board.server import serve

    console.print(f"Starting Web UI on http://{host}:{port}")
    if team:
        console.print(f"Default team: {team}")
    console.print("Press Ctrl+C to stop.")
    serve(host=host, port=port, default_team=team or "", interval=interval)


@board_app.command("attach")
def board_attach(
    team: str = typer.Argument(..., help="Team name"),
):
    """Attach to tmux session with all agent windows tiled side by side.

    Merges all agent tmux windows into a single tiled view so you can
    watch every agent working simultaneously.
    """
    from clawteam.spawn.tmux_backend import TmuxBackend

    result = TmuxBackend.attach_all(team)
    if result.startswith("Error"):
        console.print(f"[red]{result}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]OK[/green] {result}")


@board_app.command("gource")
def board_gource(
    team: str = typer.Argument(..., help="Team name"),
    export: Optional[str] = typer.Option(None, "--export", help="Export video to file (requires FFmpeg)"),
    log_only: bool = typer.Option(False, "--log-only", help="Output Gource custom log to stdout without launching"),
    live: bool = typer.Option(False, "--live", help="Stream new activity into Gource in realtime"),
    interval: float = typer.Option(2.0, "--interval", min=0.2, help="Polling interval in seconds for --live"),
    combine_worktrees: bool = typer.Option(True, "--combine-worktrees/--events-only", help="Combine git worktree logs with event log"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path for worktree discovery"),
    resolution: Optional[str] = typer.Option(None, "--resolution", "-r", help="Viewport resolution (e.g. 1920x1080)"),
    seconds_per_day: Optional[float] = typer.Option(None, "--speed", "-s", help="Seconds per day (lower = faster)"),
):
    """Launch Gource visualization of team activity.

    Visualizes ClawTeam events (task changes, messages, agent joins) and
    optionally combines git history from all agent worktrees into a unified
    Gource animation showing parallel collaboration.
    """
    import tempfile

    from clawteam.board.gource import (
        append_log_lines,
        collect_live_log_lines,
        find_gource,
        generate_combined_log,
        generate_event_log,
        launch_gource,
        stream_gource_live,
    )

    if live and export:
        _output(
            {"error": "--live cannot be used with --export"},
            lambda d: console.print(f"[red]{d['error']}[/red]"),
        )
        raise typer.Exit(1)

    # Generate log lines
    if combine_worktrees:
        lines = generate_combined_log(team, repo)
    else:
        lines = generate_event_log(team)

    if not lines:
        _output(
            {"error": f"No activity found for team '{team}'"},
            lambda d: console.print(f"[yellow]{d['error']}[/yellow]"),
        )
        raise typer.Exit(1)

    # --log-only: just print the custom log
    if log_only:
        for line in lines:
            print(line)
        return

    # Check gource is available
    gource_bin = find_gource()
    if not gource_bin:
        _output(
            {"error": "Gource not found. Install it (https://gource.io/) or set gource_path in config."},
            lambda d: console.print(f"[red]{d['error']}[/red]"),
        )
        raise typer.Exit(1)

    # Write log to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, prefix="clawteam-gource-") as f:
        f.write("\n".join(lines) + "\n")
        log_path = Path(f.name)

    try:
        title = f"ClawTeam: {team}"
        proc = launch_gource(
            log_file=None if live else log_path,
            title=title,
            resolution=resolution or "",
            seconds_per_day=seconds_per_day or 0,
            export_path=export,
            live_stream=live,
        )
        if proc is None:
            _output(
                {"error": "Failed to launch Gource" + (" (FFmpeg required for export)" if export else "")},
                lambda d: console.print(f"[red]{d['error']}[/red]"),
            )
            raise typer.Exit(1)

        if export:
            console.print(f"Exporting Gource visualization to [cyan]{export}[/cyan]...")
            proc.wait()
            console.print(f"[green]OK[/green] Video saved to {export}")
        elif live:
            if proc.stdin is None:
                console.print("[red]Failed to open live Gource stream.[/red]")
                raise typer.Exit(1)
            console.print(
                f"Gource live stream launched for team [cyan]{team}[/cyan]. "
                "Close the window or press Ctrl+C to stop."
            )
            seed_lines = collect_live_log_lines(
                set(),
                team,
                combine_worktrees=combine_worktrees,
                repo_path=repo,
            )
            append_log_lines(proc.stdin, seed_lines)
            try:
                stream_gource_live(
                    proc,
                    team,
                    combine_worktrees=combine_worktrees,
                    repo_path=repo,
                    poll_interval=interval,
                )
            except KeyboardInterrupt:
                if proc.poll() is None:
                    proc.terminate()
            finally:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.wait()
        else:
            console.print(f"Gource launched for team [cyan]{team}[/cyan]. Close the window to exit.")
            proc.wait()
    finally:
        try:
            log_path.unlink()
        except OSError:
            pass


# ============================================================================
# Workspace Commands
# ============================================================================

workspace_app = typer.Typer(help="Git worktree workspace management")
app.add_typer(workspace_app, name="workspace")


@workspace_app.command("list")
def workspace_list(
    team: str = typer.Argument(..., help="Team name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """List all active worktree workspaces for a team."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        _output({"error": "Not in a git repo"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    workspaces = ws_mgr.list_workspaces(team)
    if _json_output:
        _output(
            {"workspaces": [w.model_dump() for w in workspaces]},
            lambda d: None,
        )
        return

    if not workspaces:
        console.print(f"No active workspaces for team '{team}'.")
        return

    table = Table(title=f"Workspaces — {team}")
    table.add_column("Agent")
    table.add_column("Branch")
    table.add_column("Path")
    table.add_column("Created")
    for ws in workspaces:
        table.add_row(ws.agent_name, ws.branch_name, ws.worktree_path, format_timestamp(ws.created_at))
    console.print(table)


@workspace_app.command("checkpoint")
def workspace_checkpoint(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Commit message"),
):
    """Create a checkpoint (auto-commit) for an agent's workspace."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    committed = ws_mgr.checkpoint(team, agent, message)
    if committed:
        _output(
            {"status": "checkpoint_created", "team": team, "agent": agent},
            lambda d: console.print(f"[green]OK[/green] Checkpoint created for '{agent}'."),
        )
    else:
        _output(
            {"status": "no_changes", "team": team, "agent": agent},
            lambda d: console.print(f"[dim]No changes to checkpoint for '{agent}'.[/dim]"),
        )


@workspace_app.command("merge")
def workspace_merge(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    target: Optional[str] = typer.Option(None, "--target", help="Target branch (default: base branch)"),
    no_cleanup: bool = typer.Option(False, "--no-cleanup", help="Keep worktree after merge"),
):
    """Merge an agent's workspace branch back to the base branch."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    success, output = ws_mgr.merge_workspace(team, agent, target, cleanup_after=not no_cleanup)
    if success:
        _output(
            {"status": "merged", "team": team, "agent": agent, "output": output},
            lambda d: console.print(f"[green]OK[/green] Merged '{agent}' workspace.\n{output}"),
        )
    else:
        _output(
            {"status": "merge_failed", "team": team, "agent": agent, "output": output},
            lambda d: console.print(f"[red]Merge failed[/red] for '{agent}':\n{output}"),
        )
        raise typer.Exit(1)


@workspace_app.command("cleanup")
def workspace_cleanup(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (all if omitted)"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Clean up worktree workspace(s) — removes worktree and branch."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    if agent:
        ok = ws_mgr.cleanup_workspace(team, agent)
        if ok:
            console.print(f"[green]OK[/green] Cleaned up workspace for '{agent}'.")
        else:
            console.print(f"[yellow]No workspace found for '{agent}'.[/yellow]")
    else:
        count = ws_mgr.cleanup_team(team)
        console.print(f"[green]OK[/green] Cleaned up {count} workspace(s) for team '{team}'.")


@workspace_app.command("status")
def workspace_status(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Show git diff stat for an agent's workspace."""
    from clawteam.workspace import get_workspace_manager, git

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    ws = ws_mgr.get_workspace(team, agent)
    if ws is None:
        console.print(f"[yellow]No workspace found for '{agent}'.[/yellow]")
        raise typer.Exit(1)

    stat = git.diff_stat(Path(ws.worktree_path))
    console.print(f"[bold]Workspace status — {agent}[/bold] (branch: {ws.branch_name})")
    console.print(stat)


# ============================================================================
# Context Commands (git context layer)
# ============================================================================

context_app = typer.Typer(help="Git context: diffs, file ownership, conflicts, cross-branch log")
app.add_typer(context_app, name="context")


@context_app.command("diff")
def context_diff(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Show diff statistics for an agent's branch vs. base."""
    from clawteam.workspace.context import agent_diff

    try:
        data = agent_diff(team, agent, repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    def _human(d):
        console.print(f"[bold]{d['summary']}[/bold]")
        if d["diff_stat"]:
            console.print(d["diff_stat"])

    _output(data, _human)


@context_app.command("files")
def context_files(
    team: str = typer.Argument(..., help="Team name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Show file ownership map — which agents modify which files."""
    from clawteam.workspace.context import file_owners

    try:
        data = file_owners(team, repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    def _human(d):
        if not d:
            console.print("[dim]No modified files found.[/dim]")
            return
        table = Table(title=f"File Ownership — {team}")
        table.add_column("File", style="cyan")
        table.add_column("Agents")
        for fname, agents in sorted(d.items()):
            style = "bold red" if len(agents) > 1 else ""
            table.add_row(fname, ", ".join(agents), style=style)
        console.print(table)

    _output(data, _human)


@context_app.command("conflicts")
def context_conflicts(
    team: str = typer.Argument(..., help="Team name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Detect file overlaps across agent branches."""
    from clawteam.workspace.conflicts import detect_overlaps

    try:
        data = detect_overlaps(team, repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    def _human(d):
        if not d:
            console.print("[green]No overlaps detected.[/green]")
            return
        table = Table(title=f"File Overlaps — {team}")
        table.add_column("File", style="cyan")
        table.add_column("Agents")
        table.add_column("Severity")
        severity_styles = {"high": "bold red", "medium": "yellow", "low": "dim"}
        for item in d:
            sev = item["severity"]
            table.add_row(
                item["file"],
                ", ".join(item["agents"]),
                f"[{severity_styles.get(sev, '')}]{sev}[/{severity_styles.get(sev, '')}]",
            )
        console.print(table)

    _output(data, _human)


@context_app.command("log")
def context_log(
    team: str = typer.Argument(..., help="Team name"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max entries"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Unified cross-branch commit log for all agents."""
    from clawteam.workspace.context import cross_branch_log

    try:
        data = cross_branch_log(team, limit=limit, repo=repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    def _human(d):
        if not d:
            console.print("[dim]No commits found.[/dim]")
            return
        for entry in d:
            ts = format_timestamp(entry["timestamp"])
            console.print(
                f"[dim]{ts}[/dim] [cyan]{entry['agent']}[/cyan] "
                f"[yellow]{entry['hash'][:8]}[/yellow] {entry['message']}"
            )
            if entry["files"]:
                for f in entry["files"]:
                    console.print(f"    {f}")

    _output(data, _human)


@context_app.command("inject")
def context_inject(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Target agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Generate context block for injection into an agent's prompt."""
    from clawteam.workspace.context import inject_context

    try:
        text = inject_context(team, agent, repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    if _json_output:
        _output({"context": text}, None)
    else:
        console.print(text)


# ============================================================================
# Template Commands
# ============================================================================

template_app = typer.Typer(help="Template management")
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list():
    """List all available templates (builtin + user)."""
    from clawteam.templates import list_templates

    templates = list_templates()

    def _human(data):
        if not data:
            console.print("[dim]No templates found[/dim]")
            return
        table = Table(title="Templates")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Source", style="dim")
        for t in data:
            table.add_row(t["name"], t["description"], t["source"])
        console.print(table)

    _output(templates, _human)


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name"),
):
    """Show details of a template."""
    from clawteam.templates import load_template

    try:
        tmpl = load_template(name)
    except FileNotFoundError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = json.loads(tmpl.model_dump_json(by_alias=True))

    def _human(_data):
        console.print(f"[bold cyan]{tmpl.name}[/bold cyan] — {tmpl.description}")
        console.print(f"  Command: {' '.join(tmpl.command)}")
        console.print(f"  Backend: {tmpl.backend}")
        console.print()

        console.print("[bold]Leader:[/bold]")
        console.print(f"  {tmpl.leader.name} (type: {tmpl.leader.type})")
        console.print()

        if tmpl.agents:
            table = Table(title="Agents")
            table.add_column("Name", style="cyan")
            table.add_column("Type")
            for a in tmpl.agents:
                table.add_row(a.name, a.type)
            console.print(table)

        if tmpl.tasks:
            table = Table(title="Tasks")
            table.add_column("Subject")
            table.add_column("Owner", style="cyan")
            for t in tmpl.tasks:
                table.add_row(t.subject, t.owner)
            console.print(table)

    _output(data, _human)


# ============================================================================
# Launch Command
# ============================================================================

@app.command("launch")
def launch_team(
    template: str = typer.Argument(..., help="Template name (e.g., hedge-fund)"),
    goal: str = typer.Option("", "--goal", "-g", help="Project goal injected into agent prompts"),
    backend: Optional[str] = typer.Option(None, "--backend", "-b", help="Override backend"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Apply a named runtime profile to all agents"),
    team_name: Optional[str] = typer.Option(None, "--team-name", "--team", "-t", help="Override team name"),
    workspace: bool = typer.Option(False, "--workspace/--no-workspace", "-w"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    command_override: Optional[list[str]] = typer.Option(None, "--command", help="Override agent command"),
):
    """Launch a full agent team from a template with one command."""
    import os as _os

    from clawteam.config import get_effective
    from clawteam.spawn import get_backend
    from clawteam.spawn.profiles import apply_profile, load_profile
    from clawteam.spawn.prompt import build_agent_prompt
    from clawteam.team.manager import TeamManager
    from clawteam.team.tasks import TaskStore
    from clawteam.templates import TemplateDef, load_template, render_task

    # 1. Load template
    try:
        tmpl: TemplateDef = load_template(template)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 2. Determine team name
    t_name = team_name or f"{tmpl.name}-{uuid.uuid4().hex[:6]}"
    be_name = backend or tmpl.backend
    cmd = command_override or tmpl.command

    # 3. Create team
    leader_id = uuid.uuid4().hex[:12]
    try:
        TeamManager.create_team(
            name=t_name,
            leader_name=tmpl.leader.name,
            leader_id=leader_id,
            description=tmpl.description,
            user=_os.environ.get("CLAWTEAM_USER", ""),
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # 4. Add members
    agent_ids: dict[str, str] = {tmpl.leader.name: leader_id}
    for agent in tmpl.agents:
        aid = uuid.uuid4().hex[:12]
        agent_ids[agent.name] = aid
        TeamManager.add_member(
            team_name=t_name,
            member_name=agent.name,
            agent_id=aid,
            agent_type=agent.type,
            user=_os.environ.get("CLAWTEAM_USER", ""),
        )

    # 5. Create tasks
    ts = TaskStore(t_name)
    for task_def in tmpl.tasks:
        ts.create(
            subject=task_def.subject,
            description=task_def.description,
            owner=task_def.owner,
        )

    # 6. Get backend
    try:
        be = get_backend(be_name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Match `spawn` behavior: honor configured permission skipping for
    # template-launched agents as well.
    sp_val, _ = get_effective("skip_permissions")
    skip_permissions = str(sp_val).lower() not in ("false", "0", "no", "")

    # 7. Workspace setup (optional)
    ws_mgr = None
    if workspace:
        from clawteam.workspace import get_workspace_manager
        ws_mgr = get_workspace_manager(repo)
        if ws_mgr is None:
            console.print("[red]Not in a git repository. Use --repo or cd into a repo.[/red]")
            raise typer.Exit(1)

    # 8. Spawn all agents (leader first, then workers)
    all_agents = [tmpl.leader] + list(tmpl.agents)
    spawned: list[dict[str, str]] = []
    resolved_profile = None
    if profile:
        try:
            resolved_profile = load_profile(profile)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    for agent in all_agents:
        a_id = agent_ids[agent.name]
        a_cmd = agent.command or cmd
        a_env: dict[str, str] = {}
        if resolved_profile:
            command_seed = list(a_cmd) if (agent.command or command_override) else []
            a_cmd, a_env, _ = apply_profile(resolved_profile, command=command_seed)

        # Variable substitution
        rendered = render_task(
            agent.task,
            goal=goal,
            team_name=t_name,
            agent_name=agent.name,
        )

        # Workspace
        cwd = None
        ws_branch = ""
        if ws_mgr:
            ws_info = ws_mgr.create_workspace(
                team_name=t_name, agent_name=agent.name, agent_id=a_id,
            )
            cwd = ws_info.worktree_path
            ws_branch = ws_info.branch_name

        # Build prompt
        prompt = build_agent_prompt(
            agent_name=agent.name,
            agent_id=a_id,
            agent_type=agent.type,
            team_name=t_name,
            leader_name=tmpl.leader.name,
            task=rendered,
            user=_os.environ.get("CLAWTEAM_USER", ""),
            workspace_dir=cwd or "",
            workspace_branch=ws_branch,
            isolated_workspace=bool(cwd),
        )

        result = be.spawn(
            command=a_cmd,
            agent_name=agent.name,
            agent_id=a_id,
            agent_type=agent.type,
            team_name=t_name,
            prompt=prompt,
            env=a_env or None,
            cwd=cwd,
            skip_permissions=skip_permissions,
        )
        spawned.append({"name": agent.name, "id": a_id, "type": agent.type, "result": result})

    # 9. Output summary
    out = {
        "status": "launched",
        "team": t_name,
        "template": tmpl.name,
        "backend": be_name,
        "agents": [{"name": s["name"], "id": s["id"], "type": s["type"]} for s in spawned],
    }

    def _human(_data):
        console.print(f"\n[green bold]Team '{t_name}' launched from template '{tmpl.name}'[/green bold]\n")
        table = Table(title="Agents")
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("ID", style="dim")
        for s in spawned:
            table.add_row(s["name"], s["type"], s["id"])
        console.print(table)
        console.print()
        if be_name == "tmux":
            console.print(f"[bold]Attach:[/bold] tmux attach -t clawteam-{t_name}")
        console.print(f"[bold]Board:[/bold]  clawteam board show {t_name}")
        console.print(f"[bold]Inbox:[/bold]  clawteam inbox peek {t_name} --agent <name>")

    _output(out, _human)


if __name__ == "__main__":
    app()
