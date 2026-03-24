# SECURITY NOTES

This Windows compatibility branch is intended to be safe to share and use on another machine.

## What was checked

A repo scan was performed for:
- embedded API keys
- access tokens
- passwords / bearer tokens
- user-specific local paths
- user-specific fork / PR references in local docs

## Result

No actual live credentials were found in the Windows compatibility changes.

## Important distinctions

The upstream project contains documentation and test fixtures that reference environment variable names such as:
- `OPENROUTER_API_KEY`
- `MOONSHOT_API_KEY`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`

These are placeholders, examples, or environment variable names — not embedded secrets.

## Windows-specific operational guidance

- Prefer binding local board servers to `127.0.0.1` unless you intentionally want LAN exposure.
- Treat saved session/task/cost data as local operational metadata.
- Review spawned command profiles before distributing to other users.
- Use environment variables for provider credentials; do not hardcode them into scripts or config files you plan to share.

## Caveat

Git commit history on a public branch may still contain author metadata (name/email) from commits already created. That metadata is separate from source-file secret scanning.
