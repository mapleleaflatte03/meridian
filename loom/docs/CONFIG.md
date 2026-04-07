# Config

Loom uses a single runtime-root config file:

- `<root>/loom.toml`

The checked-in template is:

- `loom.toml.example`

## Sections

### `[runtime]`

- `mode`
- `kernel_path`
- `org_id`
- `state_dir`
- `run_dir`
- `log_dir`
- `artifact_dir`

### `[capabilities]`

- `capabilities_dir`

### `[workers]`

- `python_path`
- `typescript_path`
- `wasm_dir`

### `[service]`

- `service_http_address`
- `service_token_env`
- `service_max_jobs`
- `service_poll_seconds`
- `service_max_iterations`

### `[logging]`

- `log_level`
- `log_format`
- `log_max_bytes`
- `log_max_files`

### `[operator]`

- `profile`

### `[wasm]`

- `profile`
- `max_memory_bytes`
- `max_table_elements`
- `max_instances`
- `max_tables`
- `max_memories`
- `fuel_limit`

### `[wasm.host]`

- `backend`
- `component_model`
- `allocation`
- `isolation`
- `fuel_metering`
- `epoch_deadline_ms`

## Default root

If you do not pass `--root` and you are not standing inside a runtime root,
Loom defaults to:

- `$LOOM_ROOT` when set
- otherwise `${XDG_DATA_HOME}/meridian-loom/runtime/default`
- otherwise `$HOME/.local/share/meridian-loom/runtime/default`

## Layout defaults inside a root

- `state_dir = "state"`
- `run_dir = "run"`
- `log_dir = "logs"`
- `artifact_dir = "artifacts"`
- `capabilities_dir = "capabilities"`
- `log_max_bytes = 5242880`
- `log_max_files = 5`

## Compatibility

If Loom sees an older workspace that still uses `.loom/` and has no explicit
`state_dir`, it falls back to the legacy layout for that root. New roots use
the production-oriented layout by default.
