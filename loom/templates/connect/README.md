# Connect Templates

Operator-first adapter templates for the priority connect transports:

- `telegram.sample.json`
- `discord.sample.json`
- `whatsapp.sample.json`
- `slack.sample.json`
- `email.sample.json`
- `browser.sample.json`
- `shell.sample.json`
- `desktop.sample.json`
- `webhook.sample.json`

These are contract-shape examples for `loom connect scaffold|validate|enable|test|health`.
Each scaffold now includes a governed `security_profile` baseline and transport guard checks.
Operator retention + KPI surfaces:

- `loom connect metrics --adapter-id ...`
- `loom connect scorecard`
- `loom connect prune --adapter-id ...`
- `scripts/connect_kpi_gate.sh --root ... --adapter-id ...`

Acceptance lanes:

- `scripts/acceptance_connect_ecosystem_lane.sh`
- `scripts/acceptance_connect_telegram_lane.sh`
- `scripts/acceptance_connect_discord_lane.sh`
- `scripts/acceptance_connect_browser_lane.sh`
- `scripts/acceptance_connect_shell_lane.sh`
- `scripts/acceptance_connect_desktop_lane.sh`
- `scripts/acceptance_connect_webhook_lane.sh`
- `scripts/acceptance_connect_failure_injection_lane.sh`
- `scripts/acceptance_connect_security_lane.sh`
- `scripts/acceptance_connect_c2_matrix_lane.sh`
- `scripts/acceptance_migration_profile_lane.sh`

Migration bootstrap:

- `scripts/bootstrap_from_claw_profile.sh --profile openclaw`
- `scripts/bootstrap_from_claw_profile.sh --profile openfang`
- `scripts/bootstrap_from_claw_profile.sh --profile zeroclaw`

They do not include provider-specific defaults or secrets.
