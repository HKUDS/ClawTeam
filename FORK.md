# OpenClaw Fork Notes

This repository is an **OpenClaw-adapted fork** of [HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam).

Its purpose is to keep ClawTeam aligned with upstream while carrying a small, explicit downstream layer needed for OpenClaw integration.

## What differs from upstream

Compared with upstream `HKUDS/ClawTeam`, this fork carries a focused OpenClaw delta:

- **OpenClaw skill support** for using ClawTeam from OpenClaw-driven workflows
- **OpenClaw install/bootstrap flow** for easier setup in OpenClaw environments
- **Session isolation and adapter support** needed to run OpenClaw-integrated agent sessions cleanly and predictably

The goal is to keep this delta small, reviewable, and clearly separated from the upstream engine wherever possible.

## Sync strategy

This fork follows an **upstream-first** maintenance model:

- **Biweekly upstream merge:** regularly merge the latest `HKUDS/ClawTeam` changes into this fork
- **Cherry-pick OpenClaw delta:** replay or maintain OpenClaw-specific changes as small, auditable downstream patches instead of drifting into a long-lived fork rewrite

In practice:

1. merge upstream on a biweekly cadence (or sooner when important upstream changes land)
2. keep OpenClaw-specific behavior in a narrow integration layer
3. prefer cherry-picking or replaying downstream-only changes instead of merging legacy downstream history wholesale

## Acknowledgements

The OpenClaw integration work in this fork was **directly inspired by and partially derived from** [win4r/ClawTeam-OpenClaw](https://github.com/win4r/ClawTeam-OpenClaw). Their fork was the first to adapt ClawTeam for OpenClaw environments, covering areas such as:

- OpenClaw as a first-class spawn target
- Install scripts and exec approval bootstrapping
- Session isolation for OpenClaw agents
- Skill documentation for OpenClaw workflows

We cherry-picked and reviewed their downstream delta as the starting point for our own integration layer. Where their approach and ours diverge (e.g., we restructured session isolation into the canonical adapter pattern rather than patching engine files directly), we rewrote the implementation — but the direction and many of the ideas originated from their work.

Thank you to the win4r team for blazing the trail.

## Reference docs

For the current fork policy and delta inventory, see:

- `workflow/UPSTREAM_SYNC.md`
- `workflow/reports/win4r-delta-filelist-2026-03-22.md`

## Maintainer

- **dtzp555-max**
