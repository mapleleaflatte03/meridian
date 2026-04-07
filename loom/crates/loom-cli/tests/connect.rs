use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_connect_{}_{}_{}",
        label,
        std::process::id(),
        n
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

struct Harness {
    home: PathBuf,
    root: PathBuf,
    kernel: PathBuf,
}

impl Harness {
    fn new(label: &str) -> Self {
        let home = unique_temp_dir(label);
        let root = home.join(".local/share/meridian-loom/runtime/default");
        let kernel = home.join("kernel");
        scaffold_kernel_fixture(&kernel);
        let harness = Self { home, root, kernel };
        harness.run_ok(&[
            "init",
            "--mode",
            "embedded",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--org-id",
            "org_demo",
        ]);
        harness
    }

    fn root_str(&self) -> &str {
        self.root.to_str().expect("root str")
    }

    fn kernel_str(&self) -> &str {
        self.kernel.to_str().expect("kernel str")
    }

    fn config_home(&self) -> PathBuf {
        self.home.join(".config")
    }

    fn binary(&self) -> &'static str {
        env!("CARGO_BIN_EXE_loom")
    }

    fn base_command(&self) -> Command {
        let mut command = Command::new(self.binary());
        command.env("HOME", &self.home);
        command.env("XDG_CONFIG_HOME", self.config_home());
        command
    }

    fn run_output(&self, args: &[&str]) -> Output {
        self.base_command()
            .args(args)
            .output()
            .expect("run loom command")
    }

    fn run_ok(&self, args: &[&str]) -> String {
        let output = self.run_output(args);
        assert_success(args, &output);
        String::from_utf8_lossy(&output.stdout).to_string()
    }

    fn run_fail(&self, args: &[&str]) -> String {
        let output = self.run_output(args);
        assert!(
            !output.status.success(),
            "command {:?} unexpectedly succeeded\nstdout:\n{}\nstderr:\n{}",
            args,
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        );
        format!(
            "{}\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        )
    }

    fn json_ok(&self, args: &[&str]) -> Value {
        let output = self.run_output(args);
        assert_success(args, &output);
        serde_json::from_slice(&output.stdout).expect("parse json")
    }
}

fn assert_success(args: &[&str], output: &Output) {
    assert!(
        output.status.success(),
        "command {:?} failed\nstatus: {:?}\nstdout:\n{}\nstderr:\n{}",
        args,
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
}

fn scaffold_kernel_fixture(root: &Path) {
    let kernel_dir = root.join("kernel");
    fs::create_dir_all(&kernel_dir).expect("kernel dir");
    fs::write(
        kernel_dir.join("runtimes.json"),
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"connect fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
    )
    .expect("write runtimes");
    fs::write(
        kernel_dir.join("agent_registry.py"),
        "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 1.0}, 'runtime_binding': {'runtime_id': 'loom_native', 'runtime_label': 'Loom Native Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
    )
    .expect("write registry");
    fs::write(
        kernel_dir.join("court.py"),
        "def get_restrictions(agent_id, org_id=None):\n    return []\n",
    )
    .expect("write court");
    fs::write(
        kernel_dir.join("authority.py"),
        "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
    )
    .expect("write authority");
}

#[test]
fn connect_scaffold_creates_manifest_with_poge_standard_fields() {
    let harness = Harness::new("scaffold_manifest");
    let output = harness.json_ok(&[
        "connect",
        "scaffold",
        "--name",
        "grpc_action_adapter",
        "--transport",
        "grpc",
        "--action-schema",
        "meridian.a2a.action.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        output.get("status").and_then(Value::as_str),
        Some("connect_scaffolded")
    );
    let manifest_path = output
        .get("manifest_path")
        .and_then(Value::as_str)
        .expect("manifest_path");
    let manifest: Value =
        serde_json::from_str(&fs::read_to_string(manifest_path).expect("read connect manifest"))
            .expect("parse connect manifest");
    assert_eq!(
        manifest.get("transport").and_then(Value::as_str),
        Some("grpc")
    );
    assert_eq!(
        manifest.get("action_schema").and_then(Value::as_str),
        Some("meridian.a2a.action.v1")
    );
    assert_eq!(
        manifest
            .pointer("/poge_standard/warrant_required")
            .and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        manifest
            .pointer("/poge_standard/treasury_gate")
            .and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        manifest
            .pointer("/poge_standard/zk_settlement_compatible")
            .and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        manifest
            .pointer("/security_profile/mode")
            .and_then(Value::as_str),
        Some("governed_default")
    );
    assert_eq!(
        manifest
            .pointer("/security_profile/allow_plaintext_secrets")
            .and_then(Value::as_bool),
        Some(false)
    );
    assert_eq!(
        manifest
            .pointer("/security_profile/require_warrant")
            .and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        manifest
            .pointer("/security_profile/require_treasury_gate")
            .and_then(Value::as_bool),
        Some(true)
    );
}

#[test]
fn connect_list_surfaces_all_supported_transport_profiles() {
    let harness = Harness::new("transport_list");
    for (name, transport) in [
        ("telegram_adapter", "telegram"),
        ("discord_adapter", "discord"),
        ("browser_adapter", "browser"),
        ("shell_adapter", "shell"),
        ("desktop_adapter", "desktop"),
        ("webhook_adapter", "webhook"),
    ] {
        harness.run_ok(&[
            "connect",
            "scaffold",
            "--name",
            name,
            "--transport",
            transport,
            "--action-schema",
            "meridian.a2a.action.v1",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
    }
    let listed = harness.json_ok(&[
        "connect",
        "list",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let adapters = listed
        .get("adapters")
        .and_then(Value::as_array)
        .expect("adapters array");
    let transports = adapters
        .iter()
        .filter_map(|adapter| adapter.get("transport").and_then(Value::as_str))
        .map(|value| value.to_string())
        .collect::<BTreeSet<_>>();
    let expected = ["telegram", "discord", "browser", "shell", "desktop", "webhook"]
        .iter()
        .map(|value| value.to_string())
        .collect::<BTreeSet<_>>();
    assert_eq!(transports, expected);
}

#[test]
fn connect_scaffold_supports_growth_transports() {
    let harness = Harness::new("growth_transports");
    for (name, transport) in [
        ("whatsapp_adapter", "whatsapp"),
        ("slack_adapter", "slack"),
        ("email_adapter", "email"),
    ] {
        harness.run_ok(&[
            "connect",
            "scaffold",
            "--name",
            name,
            "--transport",
            transport,
            "--action-schema",
            "meridian.runtime.v1",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
    }

    let validated = harness.json_ok(&[
        "connect",
        "validate",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        validated.get("validation_status").and_then(Value::as_str),
        Some("pass")
    );
    let checks = validated
        .get("checks")
        .and_then(Value::as_array)
        .expect("checks");
    assert_eq!(checks.len(), 3);
    assert!(checks.iter().all(|item| {
        item.get("security_posture_ok")
            .and_then(Value::as_bool)
            .unwrap_or(false)
    }));
}

#[test]
fn connect_desktop_transport_persists_vision_events_and_metrics() {
    let harness = Harness::new("desktop_vision");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "desktop_vision_adapter",
        "--transport",
        "desktop",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "desktop-vision-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let tested = harness.json_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "desktop-vision-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        tested.get("test_status").and_then(Value::as_str),
        Some("pass")
    );
    let desktop_vision = tested
        .get("desktop_vision")
        .and_then(Value::as_object)
        .expect("desktop vision payload");
    let digest = desktop_vision
        .get("capture_digest_hex")
        .and_then(Value::as_str)
        .expect("capture digest");
    assert_eq!(digest.len(), 64);
    let desktop_history_path = tested
        .get("desktop_history_path")
        .and_then(Value::as_str)
        .expect("desktop history path");
    assert!(
        Path::new(desktop_history_path).exists(),
        "desktop history path should exist: {}",
        desktop_history_path
    );

    let diagnostics = harness.json_ok(&[
        "connect",
        "diagnostics",
        "--adapter-id",
        "desktop-vision-adapter",
        "--root",
        harness.root_str(),
        "--limit",
        "5",
        "--format",
        "json",
    ]);
    assert_eq!(
        diagnostics
            .get("desktop_recent_count")
            .and_then(Value::as_u64),
        Some(1)
    );
    assert_eq!(
        diagnostics
            .pointer("/desktop_recent/0/vision_schema")
            .and_then(Value::as_str),
        Some("meridian.desktop.vision.v1")
    );
}

#[test]
fn connect_scaffold_upserts_existing_adapter_without_duplicates() {
    let harness = Harness::new("upsert");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "shared_adapter",
        "--transport",
        "http",
        "--action-schema",
        "meridian.a2a.action.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "shared_adapter",
        "--transport",
        "mcp",
        "--action-schema",
        "meridian.a2a.action.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let listed = harness.json_ok(&[
        "connect",
        "list",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let adapters = listed
        .get("adapters")
        .and_then(Value::as_array)
        .expect("adapters array");
    let shared = adapters
        .iter()
        .filter(|adapter| {
            adapter.get("adapter_id").and_then(Value::as_str) == Some("shared-adapter")
        })
        .collect::<Vec<_>>();
    assert_eq!(shared.len(), 1, "expected single upserted adapter");
    assert_eq!(
        shared[0].get("transport").and_then(Value::as_str),
        Some("mcp")
    );
}

#[test]
fn connect_scaffold_rejects_unknown_transport() {
    let harness = Harness::new("reject_transport");
    let stderr = harness.run_fail(&[
        "connect",
        "scaffold",
        "--name",
        "bad_adapter",
        "--transport",
        "ftp",
        "--action-schema",
        "meridian.a2a.action.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        stderr.contains("unsupported transport"),
        "expected unsupported transport error, got:\n{}",
        stderr
    );
}

#[test]
fn connect_validate_migrates_registry_v1_to_v2_additive_shape() {
    let harness = Harness::new("validate_migrate_v2");
    let registry_path = Path::new(harness.root_str()).join("state/connect/registry.json");
    fs::create_dir_all(
        registry_path
            .parent()
            .expect("registry parent should exist"),
    )
    .expect("create registry directory");
    let legacy_registry = json!({
        "schema_version": "meridian.connect.registry.v1",
        "adapters": [
            {
                "schema_version": "meridian.connect.adapter.v1",
                "adapter_id": "legacy-adapter",
                "name": "legacy_adapter",
                "transport": "http",
                "action_schema": "meridian.runtime.v1",
                "status": "scaffolded",
                "created_at": "1",
                "updated_at": "1"
            }
        ]
    });
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&legacy_registry).expect("serialize v1 registry"),
    )
    .expect("write v1 registry");

    let validated = harness.json_ok(&[
        "connect",
        "validate",
        "--adapter-id",
        "legacy-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        validated.get("status").and_then(Value::as_str),
        Some("connect_validated")
    );
    assert_eq!(
        validated
            .get("registry_schema_version")
            .and_then(Value::as_str),
        Some("meridian.connect.registry.v2")
    );
    assert_eq!(
        validated
            .pointer("/migration/legacy_schema_detected")
            .and_then(Value::as_bool),
        Some(true)
    );

    let upgraded: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read upgraded registry"))
            .expect("parse upgraded registry");
    assert_eq!(
        upgraded.get("schema_version").and_then(Value::as_str),
        Some("meridian.connect.registry.v2")
    );
    assert_eq!(
        upgraded
            .pointer("/adapters/0/lifecycle/enabled")
            .and_then(Value::as_bool),
        Some(false)
    );
    assert_eq!(
        upgraded
            .pointer("/adapters/0/runtime_contract")
            .and_then(Value::as_str),
        Some("connect_runtime_contract_v2")
    );
}

#[test]
fn connect_validate_rejects_unsafe_security_matrix_for_priority_transports() {
    let harness = Harness::new("validate_security_matrix");
    let adapters = [
        ("telegram_secure_adapter", "telegram"),
        ("discord_secure_adapter", "discord"),
        ("browser_secure_adapter", "browser"),
        ("shell_secure_adapter", "shell"),
        ("desktop_secure_adapter", "desktop"),
        ("webhook_secure_adapter", "webhook"),
    ];
    for (name, transport) in adapters {
        harness.run_ok(&[
            "connect",
            "scaffold",
            "--name",
            name,
            "--transport",
            transport,
            "--action-schema",
            "meridian.runtime.v1",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
    }

    let registry_path = Path::new(harness.root_str()).join("state/connect/registry.json");
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let items = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    for adapter in items {
        let adapter_id = adapter
            .get("adapter_id")
            .and_then(Value::as_str)
            .expect("adapter_id");
        match adapter_id {
            "telegram-secure-adapter" => {
                adapter["security_profile"]["allow_plaintext_secrets"] = Value::Bool(true);
            }
            "discord-secure-adapter" => {
                adapter["security_profile"]["max_payload_bytes"] = Value::Number(0_u64.into());
            }
            "browser-secure-adapter" => {
                adapter["transport_profile"]["sandbox"] = Value::String("none".to_string());
            }
            "shell-secure-adapter" => {
                adapter["transport_profile"]["execution_mode"] =
                    Value::String("unrestricted".to_string());
            }
            "desktop-secure-adapter" => {
                adapter["transport_profile"]["control_mode"] =
                    Value::String("unrestricted_desktop_bridge".to_string());
            }
            "webhook-secure-adapter" => {
                adapter["transport_profile"]["method"] = Value::String("GET".to_string());
            }
            _ => {}
        }
    }
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let output = harness.run_output(&[
        "connect",
        "validate",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        !output.status.success(),
        "expected validation failure for unsafe security matrix"
    );
    let payload: Value = serde_json::from_slice(&output.stdout).expect("parse validate payload");
    assert_eq!(
        payload.get("status").and_then(Value::as_str),
        Some("connect_validated")
    );
    assert_eq!(
        payload.get("validation_status").and_then(Value::as_str),
        Some("fail")
    );
    assert_eq!(
        payload.get("invalid_adapters").and_then(Value::as_u64),
        Some(6)
    );
    let checks = payload
        .get("checks")
        .and_then(Value::as_array)
        .expect("checks");
    assert_eq!(checks.len(), 6);
    assert!(checks.iter().all(|item| {
        item.get("security_posture_ok")
            .and_then(Value::as_bool)
            .map(|value| !value)
            .unwrap_or(false)
    }));
}

#[test]
fn connect_enable_disable_idempotent() {
    let harness = Harness::new("enable_disable_idempotent");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "switchable_adapter",
        "--transport",
        "grpc",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let disable_noop = harness.json_ok(&[
        "connect",
        "disable",
        "--adapter-id",
        "switchable-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        disable_noop.get("mode").and_then(Value::as_str),
        Some("noop")
    );
    let enable_changed = harness.json_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "switchable-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        enable_changed.get("mode").and_then(Value::as_str),
        Some("changed")
    );

    let enable_noop = harness.json_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "switchable-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        enable_noop.get("mode").and_then(Value::as_str),
        Some("noop")
    );
    let disable_changed = harness.json_ok(&[
        "connect",
        "disable",
        "--adapter-id",
        "switchable-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        disable_changed.get("mode").and_then(Value::as_str),
        Some("changed")
    );
}

#[test]
fn connect_test_and_health_persist_history_and_latest_artifact() {
    let harness = Harness::new("test_health_history");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "history_adapter",
        "--transport",
        "mcp",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "history-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let tested = harness.json_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "history-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        tested.get("status").and_then(Value::as_str),
        Some("connect_tested")
    );
    assert_eq!(
        tested.get("test_status").and_then(Value::as_str),
        Some("pass")
    );

    let health = harness.json_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "history-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        health.get("status").and_then(Value::as_str),
        Some("connect_health")
    );
    assert_eq!(
        health.get("health_status").and_then(Value::as_str),
        Some("healthy")
    );

    let tests_history_path =
        Path::new(harness.root_str()).join("state/connect/tests/history-adapter.jsonl");
    assert!(tests_history_path.exists(), "missing tests history file");
    let history_lines = fs::read_to_string(&tests_history_path)
        .expect("read tests history")
        .lines()
        .count();
    assert!(history_lines >= 1, "expected test history entries");

    let health_path =
        Path::new(harness.root_str()).join("state/connect/health/history-adapter.json");
    assert!(health_path.exists(), "missing health file");
    let persisted_health: Value =
        serde_json::from_str(&fs::read_to_string(&health_path).expect("read health json"))
            .expect("parse health json");
    assert_eq!(
        persisted_health
            .get("health_status")
            .and_then(Value::as_str),
        Some("healthy")
    );

    let latest_artifact_path = Path::new(harness.root_str()).join("artifacts/connect/latest.json");
    let latest: Value = serde_json::from_str(
        &fs::read_to_string(&latest_artifact_path).expect("read connect latest artifact"),
    )
    .expect("parse connect latest artifact");
    assert_eq!(
        latest.get("status").and_then(Value::as_str),
        Some("connect_health")
    );
}

#[test]
fn connect_test_matrix_covers_all_transports_and_disabled_fail_path() {
    let harness = Harness::new("matrix");
    for (name, transport) in [
        ("telegram_diag_adapter", "telegram"),
        ("discord_diag_adapter", "discord"),
        ("browser_diag_adapter", "browser"),
        ("shell_diag_adapter", "shell"),
        ("desktop_diag_adapter", "desktop"),
        ("webhook_diag_adapter", "webhook"),
    ] {
        harness.run_ok(&[
            "connect",
            "scaffold",
            "--name",
            name,
            "--transport",
            transport,
            "--action-schema",
            "meridian.runtime.v1",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "enable",
            "--adapter-id",
            &name.replace('_', "-"),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        let tested = harness.json_ok(&[
            "connect",
            "test",
            "--adapter-id",
            &name.replace('_', "-"),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        assert_eq!(
            tested.get("test_status").and_then(Value::as_str),
            Some("pass")
        );
    }

    harness.run_ok(&[
        "connect",
        "disable",
        "--adapter-id",
        "telegram-diag-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let failure = harness.run_fail(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-diag-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        failure.contains("disabled"),
        "expected disabled fail path, got:\n{}",
        failure
    );
}

#[test]
fn connect_health_escalates_reconnect_then_fallback_under_repeated_failures() {
    let harness = Harness::new("reconnect_fallback");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "telegram_ops_adapter",
        "--transport",
        "telegram",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "telegram-ops-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let registry_path = Path::new(harness.root_str()).join("state/connect/registry.json");
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let adapters = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    let adapter = adapters
        .iter_mut()
        .find(|item| item.get("adapter_id").and_then(Value::as_str) == Some("telegram-ops-adapter"))
        .expect("telegram adapter");
    adapter["action_schema"] = Value::String(String::new());
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let failed = harness.run_fail(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-ops-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        failed.contains("missing_action_schema"),
        "expected missing_action_schema failure, got:\n{}",
        failed
    );

    for expected_attempt in 1..=3_u64 {
        let health = harness.json_ok(&[
            "connect",
            "health",
            "--adapter-id",
            "telegram-ops-adapter",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        assert_eq!(
            health.get("lifecycle_state").and_then(Value::as_str),
            Some("reconnecting")
        );
        assert_eq!(
            health.get("recommended_action").and_then(Value::as_str),
            Some("reconnect")
        );
        assert_eq!(
            health
                .pointer("/lifecycle_metrics/reconnect_attempts")
                .and_then(Value::as_u64),
            Some(expected_attempt)
        );
        assert_eq!(
            health
                .pointer("/lifecycle_metrics/fallback_active")
                .and_then(Value::as_bool),
            Some(true)
        );
    }

    let fallback = harness.json_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-ops-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        fallback.get("lifecycle_state").and_then(Value::as_str),
        Some("fallback")
    );
    assert_eq!(
        fallback.get("recommended_action").and_then(Value::as_str),
        Some("shadow_or_local_queue")
    );
}

#[test]
fn connect_metrics_reports_uptime_and_fallback_recovery() {
    let harness = Harness::new("metrics");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "telegram_metrics_adapter",
        "--transport",
        "telegram",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "telegram-metrics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-metrics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-metrics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let registry_path = Path::new(harness.root_str()).join("state/connect/registry.json");
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let adapters = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    let adapter = adapters
        .iter_mut()
        .find(|item| {
            item.get("adapter_id").and_then(Value::as_str) == Some("telegram-metrics-adapter")
        })
        .expect("telegram metrics adapter");
    adapter["action_schema"] = Value::String(String::new());
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let _ = harness.run_fail(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-metrics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    for _ in 0..4 {
        let _ = harness.json_ok(&[
            "connect",
            "health",
            "--adapter-id",
            "telegram-metrics-adapter",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
    }

    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let adapters = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    let adapter = adapters
        .iter_mut()
        .find(|item| {
            item.get("adapter_id").and_then(Value::as_str) == Some("telegram-metrics-adapter")
        })
        .expect("telegram metrics adapter");
    adapter["action_schema"] = Value::String("meridian.runtime.v1".to_string());
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    harness.run_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-metrics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-metrics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let metrics = harness.json_ok(&[
        "connect",
        "metrics",
        "--adapter-id",
        "telegram-metrics-adapter",
        "--retention-days",
        "30",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        metrics.get("status").and_then(Value::as_str),
        Some("connect_metrics")
    );
    assert_eq!(
        metrics.get("adapter_id").and_then(Value::as_str),
        Some("telegram-metrics-adapter")
    );
    assert!(
        metrics
            .get("tests_total")
            .and_then(Value::as_u64)
            .unwrap_or_default()
            >= 2
    );
    assert!(
        metrics
            .get("fallback_events")
            .and_then(Value::as_u64)
            .unwrap_or_default()
            >= 1
    );
    assert!(
        metrics
            .get("fallback_recoveries")
            .and_then(Value::as_u64)
            .unwrap_or_default()
            >= 1
    );
    assert!(
        metrics
            .get("uptime_ratio")
            .and_then(Value::as_f64)
            .unwrap_or_default()
            > 0.0
    );
    assert!(
        metrics
            .get("fallback_success_ratio")
            .and_then(Value::as_f64)
            .unwrap_or_default()
            > 0.0
    );
}

#[test]
fn connect_prune_removes_stale_history_events() {
    let harness = Harness::new("prune");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "telegram_prune_adapter",
        "--transport",
        "telegram",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "telegram-prune-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-prune-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-prune-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let tests_path =
        Path::new(harness.root_str()).join("state/connect/tests/telegram-prune-adapter.jsonl");
    let lifecycle_path =
        Path::new(harness.root_str()).join("state/connect/lifecycle/telegram-prune-adapter.jsonl");
    fs::write(
        &tests_path,
        "{\"schema_version\":\"meridian.connect.test_event.v1\",\"adapter_id\":\"telegram-prune-adapter\",\"result\":\"pass\",\"reason\":\"stale\",\"tested_at\":\"1\"}\n\
{\"schema_version\":\"meridian.connect.test_event.v1\",\"adapter_id\":\"telegram-prune-adapter\",\"result\":\"pass\",\"reason\":\"fresh\",\"tested_at\":\"9999999999\"}\n",
    )
    .expect("write tests history");
    fs::write(
        &lifecycle_path,
        "{\"schema_version\":\"meridian.connect.lifecycle_event.v1\",\"adapter_id\":\"telegram-prune-adapter\",\"state\":\"fallback\",\"action\":\"health_fallback\",\"reason\":\"stale\",\"recorded_at\":\"1\"}\n\
{\"schema_version\":\"meridian.connect.lifecycle_event.v1\",\"adapter_id\":\"telegram-prune-adapter\",\"state\":\"ready\",\"action\":\"health_ok\",\"reason\":\"fresh\",\"recorded_at\":\"9999999999\"}\n",
    )
    .expect("write lifecycle history");

    let pruned = harness.json_ok(&[
        "connect",
        "prune",
        "--adapter-id",
        "telegram-prune-adapter",
        "--retention-days",
        "30",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        pruned.get("status").and_then(Value::as_str),
        Some("connect_pruned")
    );
    assert_eq!(
        pruned
            .get("removed_tests_entries")
            .and_then(Value::as_u64)
            .unwrap_or_default(),
        1
    );
    assert_eq!(
        pruned
            .get("removed_lifecycle_entries")
            .and_then(Value::as_u64)
            .unwrap_or_default(),
        1
    );

    let tests_after = fs::read_to_string(&tests_path).expect("read tests after prune");
    assert!(tests_after.contains("\"reason\":\"fresh\""));
    assert!(!tests_after.contains("\"reason\":\"stale\""));

    let lifecycle_after = fs::read_to_string(&lifecycle_path).expect("read lifecycle after prune");
    assert!(lifecycle_after.contains("\"reason\":\"fresh\""));
    assert!(!lifecycle_after.contains("\"reason\":\"stale\""));
}

#[test]
fn connect_scorecard_rejects_unexpected_argument_tokens() {
    let harness = Harness::new("scorecard_unexpected");
    let failure = harness.run_fail(&[
        "connect",
        "scorecard",
        "--retention-days",
        "30",
        "--fix",
        "__unexpected_token__",
        "--root",
        harness.root_str(),
    ]);
    assert!(
        failure.contains("unexpected argument '__unexpected_token__' for `loom connect scorecard`"),
        "unexpected failure output:\n{failure}"
    );
}

#[test]
fn connect_scorecard_empty_registry_returns_actionable_hint() {
    let harness = Harness::new("scorecard_empty");
    let failure = harness.run_fail(&[
        "connect",
        "scorecard",
        "--retention-days",
        "30",
        "--root",
        harness.root_str(),
    ]);
    assert!(
        failure.contains("connect scorecard found no adapters; run `loom connect scaffold"),
        "unexpected failure output:\n{failure}"
    );
}

#[test]
fn connect_scorecard_aggregates_adapter_kpis() {
    let harness = Harness::new("scorecard");
    for (name, transport) in [
        ("telegram_score_adapter", "telegram"),
        ("discord_score_adapter", "discord"),
    ] {
        harness.run_ok(&[
            "connect",
            "scaffold",
            "--name",
            name,
            "--transport",
            transport,
            "--action-schema",
            "meridian.runtime.v1",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "enable",
            "--adapter-id",
            &name.replace('_', "-"),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "test",
            "--adapter-id",
            &name.replace('_', "-"),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "health",
            "--adapter-id",
            &name.replace('_', "-"),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
    }

    let scorecard = harness.json_ok(&[
        "connect",
        "scorecard",
        "--retention-days",
        "30",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        scorecard.get("status").and_then(Value::as_str),
        Some("connect_scorecard")
    );
    assert_eq!(
        scorecard
            .get("total_adapters")
            .and_then(Value::as_u64)
            .unwrap_or_default(),
        2
    );
    assert_eq!(
        scorecard
            .get("overall_status")
            .and_then(Value::as_str)
            .map(|value| value == "healthy" || value == "degraded"),
        Some(true)
    );
    let adapters = scorecard
        .get("adapters")
        .and_then(Value::as_array)
        .expect("adapters");
    assert_eq!(adapters.len(), 2);
    assert!(adapters.iter().all(|adapter| {
        adapter
            .get("uptime_ratio")
            .and_then(Value::as_f64)
            .is_some()
    }));
    assert!(adapters.iter().all(|adapter| {
        adapter
            .get("target_uptime_met")
            .and_then(Value::as_bool)
            .is_some()
    }));
}

#[test]
fn connect_scorecard_fix_applies_remediation_for_degraded_adapter() {
    let harness = Harness::new("scorecard_fix");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "telegram_fix_adapter",
        "--transport",
        "telegram",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "telegram-fix-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-fix-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-fix-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let registry_path = Path::new(harness.root_str()).join("state/connect/registry.json");
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let adapters = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    let adapter = adapters
        .iter_mut()
        .find(|item| item.get("adapter_id").and_then(Value::as_str) == Some("telegram-fix-adapter"))
        .expect("telegram fix adapter");
    adapter["action_schema"] = Value::String(String::new());
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let _ = harness.run_fail(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-fix-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    for _ in 0..4 {
        let _ = harness.json_ok(&[
            "connect",
            "health",
            "--adapter-id",
            "telegram-fix-adapter",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
    }

    let scorecard = harness.json_ok(&[
        "connect",
        "scorecard",
        "--retention-days",
        "30",
        "--fix",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        scorecard.get("status").and_then(Value::as_str),
        Some("connect_scorecard")
    );
    assert!(
        scorecard
            .get("remediations_applied")
            .and_then(Value::as_u64)
            .unwrap_or_default()
            >= 1
    );

    let registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let adapters = registry
        .get("adapters")
        .and_then(Value::as_array)
        .expect("adapters");
    let adapter = adapters
        .iter()
        .find(|item| item.get("adapter_id").and_then(Value::as_str) == Some("telegram-fix-adapter"))
        .expect("telegram fix adapter");
    assert_eq!(
        adapter
            .pointer("/lifecycle/reconnect_attempts")
            .and_then(Value::as_u64),
        Some(0)
    );
    assert_eq!(
        adapter.pointer("/fallback/active").and_then(Value::as_bool),
        Some(false)
    );

    let lifecycle_path =
        Path::new(harness.root_str()).join("state/connect/lifecycle/telegram-fix-adapter.jsonl");
    let lifecycle_history = fs::read_to_string(&lifecycle_path).expect("read lifecycle");
    assert!(
        lifecycle_history.contains("\"action\":\"scorecard_fix\""),
        "expected scorecard_fix lifecycle action in history"
    );
}

#[test]
fn connect_scorecard_fix_applies_security_baseline_for_priority_transports() {
    let harness = Harness::new("scorecard_security_fix");
    let adapters = [
        ("telegram_security_adapter", "telegram"),
        ("discord_security_adapter", "discord"),
        ("browser_security_adapter", "browser"),
        ("shell_security_adapter", "shell"),
        ("desktop_security_adapter", "desktop"),
        ("webhook_security_adapter", "webhook"),
    ];

    for (name, transport) in adapters {
        let adapter_id = name.replace('_', "-");
        harness.run_ok(&[
            "connect",
            "scaffold",
            "--name",
            name,
            "--transport",
            transport,
            "--action-schema",
            "meridian.runtime.v1",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "enable",
            "--adapter-id",
            adapter_id.as_str(),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "test",
            "--adapter-id",
            adapter_id.as_str(),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "health",
            "--adapter-id",
            adapter_id.as_str(),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
    }

    let registry_path = Path::new(harness.root_str()).join("state/connect/registry.json");
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let items = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    for adapter in items {
        let adapter_id = adapter
            .get("adapter_id")
            .and_then(Value::as_str)
            .expect("adapter_id");
        match adapter_id {
            "telegram-security-adapter" => {
                adapter["security_profile"]["allow_plaintext_secrets"] = Value::Bool(true);
            }
            "discord-security-adapter" => {
                adapter["security_profile"]["max_payload_bytes"] = Value::Number(0_u64.into());
            }
            "browser-security-adapter" => {
                adapter["transport_profile"]["sandbox"] = Value::String("none".to_string());
            }
            "shell-security-adapter" => {
                adapter["transport_profile"]["execution_mode"] =
                    Value::String("unrestricted".to_string());
            }
            "desktop-security-adapter" => {
                adapter["transport_profile"]["control_mode"] =
                    Value::String("unrestricted_desktop_bridge".to_string());
            }
            "webhook-security-adapter" => {
                adapter["transport_profile"]["method"] = Value::String("GET".to_string());
            }
            _ => {}
        }
    }
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let scorecard = harness.json_ok(&[
        "connect",
        "scorecard",
        "--retention-days",
        "30",
        "--fix",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        scorecard.get("status").and_then(Value::as_str),
        Some("connect_scorecard")
    );
    assert_eq!(
        scorecard.get("overall_status").and_then(Value::as_str),
        Some("degraded")
    );
    let remediation_actions = scorecard
        .get("remediation_actions")
        .and_then(Value::as_array)
        .expect("remediation actions");
    let security_actions = remediation_actions
        .iter()
        .filter(|item| {
            item.get("action").and_then(Value::as_str) == Some("apply_security_baseline")
        })
        .count();
    assert!(
        security_actions >= 6,
        "expected at least six apply_security_baseline actions, got {}",
        security_actions
    );

    let validated = harness.json_ok(&[
        "connect",
        "validate",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        validated.get("validation_status").and_then(Value::as_str),
        Some("pass")
    );
}

#[test]
fn connect_diagnostics_returns_recent_test_and_lifecycle_history() {
    let harness = Harness::new("diagnostics");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "telegram_diagnostics_adapter",
        "--transport",
        "telegram",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "telegram-diagnostics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-diagnostics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-diagnostics-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let diagnostics = harness.json_ok(&[
        "connect",
        "diagnostics",
        "--adapter-id",
        "telegram-diagnostics-adapter",
        "--limit",
        "5",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        diagnostics.get("status").and_then(Value::as_str),
        Some("connect_diagnostics")
    );
    assert_eq!(
        diagnostics.get("adapter_id").and_then(Value::as_str),
        Some("telegram-diagnostics-adapter")
    );
    assert_eq!(diagnostics.get("limit").and_then(Value::as_u64), Some(5));
    assert_eq!(
        diagnostics
            .get("tests_recent")
            .and_then(Value::as_array)
            .map(|items| !items.is_empty()),
        Some(true)
    );
    assert_eq!(
        diagnostics
            .get("lifecycle_recent")
            .and_then(Value::as_array)
            .map(|items| !items.is_empty()),
        Some(true)
    );
    assert!(
        diagnostics.get("health_snapshot").is_some(),
        "expected health snapshot in diagnostics payload"
    );
}

#[test]
fn connect_failure_injection_matrix_recovers_priority_transports() {
    let harness = Harness::new("failure_injection_matrix");
    let adapters = [
        ("telegram_fail_adapter", "telegram"),
        ("discord_fail_adapter", "discord"),
        ("browser_fail_adapter", "browser"),
        ("shell_fail_adapter", "shell"),
        ("desktop_fail_adapter", "desktop"),
        ("webhook_fail_adapter", "webhook"),
    ];

    for (name, transport) in adapters {
        let adapter_id = name.replace('_', "-");
        harness.run_ok(&[
            "connect",
            "scaffold",
            "--name",
            name,
            "--transport",
            transport,
            "--action-schema",
            "meridian.runtime.v1",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "enable",
            "--adapter-id",
            adapter_id.as_str(),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "test",
            "--adapter-id",
            adapter_id.as_str(),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        harness.run_ok(&[
            "connect",
            "health",
            "--adapter-id",
            adapter_id.as_str(),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
    }

    let registry_path = Path::new(harness.root_str()).join("state/connect/registry.json");
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let items = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    for adapter in items {
        adapter["action_schema"] = Value::String(String::new());
    }
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    for (name, _) in adapters {
        let adapter_id = name.replace('_', "-");
        let fail_output = harness.run_fail(&[
            "connect",
            "test",
            "--adapter-id",
            adapter_id.as_str(),
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        assert!(
            fail_output.contains("missing_action_schema"),
            "expected missing_action_schema for {adapter_id}, got:\n{fail_output}"
        );
        for _ in 0..4 {
            let _ = harness.json_ok(&[
                "connect",
                "health",
                "--adapter-id",
                adapter_id.as_str(),
                "--root",
                harness.root_str(),
                "--format",
                "json",
            ]);
        }
    }

    let scorecard = harness.json_ok(&[
        "connect",
        "scorecard",
        "--retention-days",
        "30",
        "--fix",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        scorecard.get("status").and_then(Value::as_str),
        Some("connect_scorecard")
    );
    assert!(
        scorecard
            .get("remediations_applied")
            .and_then(Value::as_u64)
            .unwrap_or_default()
            >= 6
    );

    let registry_after: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let items = registry_after
        .get("adapters")
        .and_then(Value::as_array)
        .expect("adapters");
    for (name, _) in adapters {
        let adapter_id = name.replace('_', "-");
        let adapter = items
            .iter()
            .find(|item| {
                item.get("adapter_id").and_then(Value::as_str) == Some(adapter_id.as_str())
            })
            .expect("adapter in registry after fix");
        assert_eq!(
            adapter
                .pointer("/lifecycle/reconnect_attempts")
                .and_then(Value::as_u64),
            Some(0),
            "expected reconnect_attempts reset for {}",
            adapter_id
        );
        assert_eq!(
            adapter.pointer("/fallback/active").and_then(Value::as_bool),
            Some(false),
            "expected fallback reset for {}",
            adapter_id
        );

        let lifecycle_path = Path::new(harness.root_str())
            .join("state/connect/lifecycle")
            .join(format!("{adapter_id}.jsonl"));
        let lifecycle_history =
            fs::read_to_string(&lifecycle_path).expect("read lifecycle after remediation");
        assert!(
            lifecycle_history.contains("\"action\":\"scorecard_fix\""),
            "expected scorecard_fix lifecycle action for {}",
            adapter_id
        );
    }
}

#[test]
fn connect_c2_hardening_matrix_enforces_rate_limit_malformed_and_sanction_path() {
    let harness = Harness::new("c2_hardening_matrix");

    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "telegram_c2_rate_adapter",
        "--transport",
        "telegram",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "telegram-c2-rate-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let registry_path = Path::new(harness.root_str()).join("state/connect/registry.json");
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let adapters = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    let rate_adapter = adapters
        .iter_mut()
        .find(|item| {
            item.get("adapter_id").and_then(Value::as_str) == Some("telegram-c2-rate-adapter")
        })
        .expect("rate adapter");
    rate_adapter["transport_profile"]["rate_limit_per_minute"] = Value::Number(1_u64.into());
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let _ = harness.json_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-c2-rate-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let rate_limit_output = harness.run_output(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-c2-rate-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        !rate_limit_output.status.success(),
        "expected rate-limit failure"
    );
    let rate_limit_payload: Value =
        serde_json::from_slice(&rate_limit_output.stdout).expect("parse rate-limit payload");
    assert_eq!(
        rate_limit_payload
            .get("test_reason")
            .and_then(Value::as_str)
            .map(|value| value.starts_with("rate_limited:")),
        Some(true)
    );

    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "webhook_c2_malformed_adapter",
        "--transport",
        "webhook",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "webhook-c2-malformed-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let adapters = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    let malformed_adapter = adapters
        .iter_mut()
        .find(|item| {
            item.get("adapter_id").and_then(Value::as_str) == Some("webhook-c2-malformed-adapter")
        })
        .expect("malformed adapter");
    malformed_adapter["transport_profile"]["force_malformed_payload"] = Value::Bool(true);
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let malformed_output = harness.run_output(&[
        "connect",
        "test",
        "--adapter-id",
        "webhook-c2-malformed-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        !malformed_output.status.success(),
        "expected malformed payload failure"
    );
    let malformed_payload: Value =
        serde_json::from_slice(&malformed_output.stdout).expect("parse malformed payload");
    assert_eq!(
        malformed_payload.get("test_reason").and_then(Value::as_str),
        Some("malformed_payload")
    );
    let malformed_sanctions = Path::new(harness.root_str())
        .join("state/connect/sanctions/webhook-c2-malformed-adapter.jsonl");
    let malformed_sanctions_raw =
        fs::read_to_string(&malformed_sanctions).expect("read malformed sanctions");
    assert!(
        malformed_sanctions_raw.contains("\"sanction_kind\":\"malformed_payload\""),
        "expected malformed_payload sanction event"
    );

    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "telegram_c2_storm_adapter",
        "--transport",
        "telegram",
        "--action-schema",
        "meridian.runtime.v1",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "enable",
        "--adapter-id",
        "telegram-c2-storm-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let mut registry: Value =
        serde_json::from_str(&fs::read_to_string(&registry_path).expect("read registry"))
            .expect("parse registry");
    let adapters = registry
        .get_mut("adapters")
        .and_then(Value::as_array_mut)
        .expect("adapters");
    let storm_adapter = adapters
        .iter_mut()
        .find(|item| {
            item.get("adapter_id").and_then(Value::as_str) == Some("telegram-c2-storm-adapter")
        })
        .expect("storm adapter");
    storm_adapter["action_schema"] = Value::String(String::new());
    storm_adapter["lifecycle"]["reconnect_attempts_max"] = Value::Number(1_u64.into());
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let _ = harness.run_fail(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-c2-storm-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let _ = harness.json_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-c2-storm-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let storm_health = harness.json_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-c2-storm-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        storm_health.get("lifecycle_state").and_then(Value::as_str),
        Some("fallback")
    );
    let storm_health = harness.json_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-c2-storm-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        storm_health.get("lifecycle_state").and_then(Value::as_str),
        Some("sanctioned")
    );
    assert_eq!(
        storm_health.get("sanction_status").and_then(Value::as_str),
        Some("reconnect_storm")
    );
    let storm_sanctions = Path::new(harness.root_str())
        .join("state/connect/sanctions/telegram-c2-storm-adapter.jsonl");
    let storm_sanctions_raw = fs::read_to_string(&storm_sanctions).expect("read storm sanctions");
    assert!(
        storm_sanctions_raw.contains("\"sanction_kind\":\"reconnect_storm\""),
        "expected reconnect_storm sanction event"
    );

    let scorecard = harness.json_ok(&[
        "connect",
        "scorecard",
        "--retention-days",
        "30",
        "--fix",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let remediation_actions = scorecard
        .get("remediation_actions")
        .and_then(Value::as_array)
        .expect("remediation actions");
    assert!(remediation_actions.iter().any(|item| {
        item.get("adapter_id").and_then(Value::as_str) == Some("telegram-c2-storm-adapter")
            && item.get("action").and_then(Value::as_str) == Some("manual_court_review_required")
    }));
}

#[test]
fn connect_unknown_subcommand_shows_available_commands() {
    let h = Harness::new("unknown_subcmd");
    let output = h.run_fail(&["connect", "foobar", "--root", h.root_str()]);
    assert!(
        output.contains("unknown connect subcommand 'foobar'"),
        "should echo the bad subcommand name: {output}"
    );
    assert!(
        output.contains("scaffold") && output.contains("scorecard"),
        "should list available subcommands: {output}"
    );
}

#[test]
fn connect_adapter_not_found_suggests_list() {
    let h = Harness::new("not_found_hint");
    let output = h.run_fail(&[
        "connect",
        "health",
        "--adapter-id",
        "nonexistent",
        "--root",
        h.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        output.contains("not found") && output.contains("loom connect list"),
        "adapter-not-found should suggest `loom connect list`: {output}"
    );
}

#[test]
fn connect_missing_adapter_id_suggests_help() {
    let h = Harness::new("missing_flag");
    let output = h.run_fail(&[
        "connect",
        "health",
        "--root",
        h.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        output.contains("missing required flag") && output.contains("--help"),
        "missing flag error should mention --help: {output}"
    );
}

#[test]
fn connect_help_prints_usage() {
    let h = Harness::new("help_flag");
    let output = h.run_ok(&["connect", "--help"]);
    assert!(
        output.contains("COMMANDS:") && output.contains("scaffold"),
        "help output should list commands: {output}"
    );
}

#[test]
fn doctor_json_fix_emits_valid_json() {
    let h = Harness::new("doctor_json");
    let raw = h.run_ok(&["doctor", "--root", h.root_str(), "--format", "json", "--fix"]);
    let parsed: Value = serde_json::from_str(raw.trim())
        .unwrap_or_else(|e| panic!("doctor --fix JSON is invalid: {e}\nraw output:\n{raw}"));
    assert!(
        parsed.get("checks").is_some(),
        "JSON output should have 'checks' key: {parsed}"
    );
    assert!(
        parsed.get("fix_results").is_some(),
        "JSON output should have 'fix_results' key: {parsed}"
    );
    let fix_results = parsed["fix_results"].as_array().expect("fix_results should be array");
    assert!(
        !fix_results.is_empty(),
        "fix_results should contain at least one entry"
    );
}

#[test]
fn doctor_human_shows_summary_and_next_step() {
    let h = Harness::new("doctor_human");
    let output = h.run_ok(&["doctor", "--root", h.root_str(), "--format", "human"]);
    assert!(
        output.contains("overall:") && output.contains("next_step:"),
        "doctor human should include summary and next_step: {output}"
    );
}

#[test]
fn unknown_top_level_command_suggests_help() {
    let h = Harness::new("unknown_cmd");
    let output = h.run_fail(&["nonexistent-command"]);
    assert!(
        output.contains("unknown command") && output.contains("--help"),
        "unknown command error should suggest --help: {output}"
    );
}

#[test]
fn connect_health_includes_operator_next_step() {
    let harness = Harness::new("health_next_step");
    harness.run_ok(&[
        "connect", "scaffold", "--name", "telegram_health_step",
        "--transport", "telegram", "--action-schema", "meridian.runtime.v1",
        "--root", harness.root_str(), "--format", "json",
    ]);
    harness.run_ok(&[
        "connect", "enable", "--adapter-id", "telegram-health-step",
        "--root", harness.root_str(), "--format", "json",
    ]);
    harness.run_ok(&[
        "connect", "test", "--adapter-id", "telegram-health-step",
        "--root", harness.root_str(), "--format", "json",
    ]);
    let health = harness.json_ok(&[
        "connect", "health", "--adapter-id", "telegram-health-step",
        "--root", harness.root_str(), "--format", "json",
    ]);
    assert_eq!(health.get("health_status").and_then(Value::as_str), Some("healthy"));
    let next_step = health.get("operator_next_step").and_then(Value::as_str).expect("operator_next_step");
    assert!(next_step.contains("loom connect"), "operator_next_step should be actionable: {next_step}");
}

#[test]
fn connect_diagnostics_includes_operator_next_step() {
    let harness = Harness::new("diag_next_step");
    harness.run_ok(&[
        "connect", "scaffold", "--name", "webhook_diag_step",
        "--transport", "webhook", "--action-schema", "meridian.runtime.v1",
        "--root", harness.root_str(), "--format", "json",
    ]);
    let diag = harness.json_ok(&[
        "connect", "diagnostics", "--adapter-id", "webhook-diag-step",
        "--root", harness.root_str(), "--format", "json",
    ]);
    let next_step = diag.get("operator_next_step").and_then(Value::as_str).expect("operator_next_step");
    assert!(
        next_step.contains("loom connect health") && next_step.contains("webhook-diag-step"),
        "diagnostics operator_next_step should point to health command: {next_step}"
    );
}
