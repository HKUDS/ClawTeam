from __future__ import annotations

from pathlib import Path

from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import MessageType
from clawteam.team.plan import PlanManager, stage_launch_plan


def _create_team(tmp_path: Path, monkeypatch, team_name: str) -> None:
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name=team_name,
        leader_name="leader",
        leader_id=f"{team_name}-leader-001",
    )


def test_submit_plan_stores_under_team_directory(
    monkeypatch,
    tmp_path: Path,
):
    _create_team(tmp_path, monkeypatch, "alpha")

    mailbox = MailboxManager("alpha")
    plan_id = PlanManager("alpha", mailbox).submit_plan(
        agent_name="worker",
        leader_name="leader",
        plan_content="team-scoped plan",
    )

    team_plan_path = tmp_path / "plans" / "alpha" / f"worker-{plan_id}.md"
    legacy_plan_path = tmp_path / "plans" / f"worker-{plan_id}.md"
    event_log = mailbox.get_event_log(limit=1)

    assert team_plan_path.read_text(encoding="utf-8") == "team-scoped plan"
    assert not legacy_plan_path.exists()
    assert PlanManager.get_plan(plan_id, "worker", team_name="alpha") == "team-scoped plan"
    assert event_log[0].plan_file == str(team_plan_path)
    assert event_log[0].plan is None


def test_get_plan_falls_back_to_legacy_flat_layout(
    monkeypatch,
    tmp_path: Path,
):
    _create_team(tmp_path, monkeypatch, "alpha")

    legacy_plan_path = tmp_path / "plans" / "worker-legacy123.md"
    legacy_plan_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_plan_path.write_text("legacy plan", encoding="utf-8")

    assert PlanManager.get_plan("legacy123", "worker", team_name="alpha") == "legacy plan"


def test_get_plan_supports_team_scoped_storage_without_team_name(
    monkeypatch,
    tmp_path: Path,
):
    _create_team(tmp_path, monkeypatch, "alpha")

    mailbox = MailboxManager("alpha")
    plan_id = PlanManager("alpha", mailbox).submit_plan(
        agent_name="worker",
        leader_name="leader",
        plan_content="team-scoped plan",
    )

    assert PlanManager.get_plan(plan_id, "worker") == "team-scoped plan"


def test_cleanup_only_removes_team_plans_and_referenced_legacy_files(
    monkeypatch,
    tmp_path: Path,
):
    _create_team(tmp_path, monkeypatch, "alpha")
    _create_team(tmp_path, monkeypatch, "beta")

    alpha_mailbox = MailboxManager("alpha")
    beta_mailbox = MailboxManager("beta")

    alpha_plan_id = PlanManager("alpha", alpha_mailbox).submit_plan(
        agent_name="worker",
        leader_name="leader",
        plan_content="alpha current plan",
    )
    beta_plan_id = PlanManager("beta", beta_mailbox).submit_plan(
        agent_name="worker",
        leader_name="leader",
        plan_content="beta current plan",
    )

    legacy_alpha = tmp_path / "plans" / "worker-legacy-alpha.md"
    legacy_beta = tmp_path / "plans" / "worker-legacy-beta.md"
    legacy_alpha.write_text("alpha legacy plan", encoding="utf-8")
    legacy_beta.write_text("beta legacy plan", encoding="utf-8")

    alpha_mailbox.send(
        from_agent="worker",
        to="leader",
        msg_type=MessageType.plan_approval_request,
        request_id="legacy-alpha",
        plan_file=str(legacy_alpha),
        summary="alpha legacy",
        plan="alpha legacy plan",
    )
    beta_mailbox.send(
        from_agent="worker",
        to="leader",
        msg_type=MessageType.plan_approval_request,
        request_id="legacy-beta",
        plan_file=str(legacy_beta),
        summary="beta legacy",
        plan="beta legacy plan",
    )

    assert TeamManager.cleanup("alpha") is True

    assert not (tmp_path / "teams" / "alpha").exists()
    assert not (tmp_path / "plans" / "alpha" / f"worker-{alpha_plan_id}.md").exists()
    assert not legacy_alpha.exists()

    assert (tmp_path / "teams" / "beta").exists()
    assert (tmp_path / "plans" / "beta" / f"worker-{beta_plan_id}.md").exists()
    assert legacy_beta.exists()


def test_cleanup_nonexistent_team_preserves_other_team_plans(
    monkeypatch,
    tmp_path: Path,
):
    _create_team(tmp_path, monkeypatch, "alpha")
    _create_team(tmp_path, monkeypatch, "beta")

    beta_mailbox = MailboxManager("beta")
    beta_plan_id = PlanManager("beta", beta_mailbox).submit_plan(
        agent_name="worker",
        leader_name="leader",
        plan_content="beta current plan",
    )

    legacy_beta = tmp_path / "plans" / "worker-legacy-beta.md"
    legacy_beta.write_text("beta legacy plan", encoding="utf-8")
    beta_mailbox.send(
        from_agent="worker",
        to="leader",
        msg_type=MessageType.plan_approval_request,
        request_id="legacy-beta",
        plan_file=str(legacy_beta),
        summary="beta legacy",
        plan="beta legacy plan",
    )

    assert TeamManager.cleanup("ghost-team") is False

    assert (tmp_path / "teams" / "beta").exists()
    assert (tmp_path / "plans" / "beta" / f"worker-{beta_plan_id}.md").exists()
    assert legacy_beta.exists()


def test_stage_launch_plan_copies_external_artifact_into_team_directory(
    monkeypatch,
    tmp_path: Path,
):
    _create_team(tmp_path, monkeypatch, "alpha")

    source_plan = tmp_path / "workspace-plan.md"
    source_plan.write_text("# Launch plan\nUse artifact-backed intake.\n", encoding="utf-8")

    staged_path = stage_launch_plan("alpha", source_plan)

    assert staged_path == tmp_path / "plans" / "alpha" / "launch-plan.md"
    assert staged_path.read_text(encoding="utf-8") == source_plan.read_text(encoding="utf-8")


def test_submit_plan_keeps_mailbox_event_artifact_first(
    monkeypatch,
    tmp_path: Path,
):
    _create_team(tmp_path, monkeypatch, "alpha")

    mailbox = MailboxManager("alpha")
    plan_id = PlanManager("alpha", mailbox).submit_plan(
        agent_name="worker",
        leader_name="leader",
        plan_content="# Plan\nUse the artifact file.\n",
        summary="artifact-backed plan",
    )

    [event] = mailbox.get_event_log(limit=1)
    expected_path = tmp_path / "plans" / "alpha" / f"worker-{plan_id}.md"

    assert event.plan_file == str(expected_path)
    assert event.summary == "artifact-backed plan"
    assert event.plan is None
