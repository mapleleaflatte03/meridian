use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_extension_{}_{}_{}",
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
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"extension fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
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

fn write_manifest(path: &Path, payload: &Value) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("manifest parent");
    }
    fs::write(
        path,
        serde_json::to_string_pretty(payload).expect("manifest json") + "\n",
    )
    .expect("write manifest");
}

fn sample_manifest(extension_id: &str) -> Value {
    json!({
        "schema_version": "meridian.extension.contract.v1",
        "extension_id": extension_id,
        "name": "Observability Pack",
        "version": "1.0.0",
        "description": "Operator diagnostics and governed proof helpers.",
        "entrypoint": {
            "kind": "skill_pack",
            "path": "skills/observability_pack"
        },
        "capabilities": [
            {
                "id": "loom.observe.health.v1",
                "kind": "operator_diagnostic",
                "description": "Emits compact health snapshots."
            }
        ],
        "permissions": {
            "filesystem": ["read:state/*", "write:artifacts/extensions/*"],
            "network": ["egress:https://extensions.example"],
            "governance": {
                "requires_warrant": true,
                "requires_authority_check": true,
                "requires_court_check": true,
                "requires_treasury_gate": true
            }
        },
        "provider_config": {
            "mode": "agnostic",
            "profiles": [
                {
                    "profile_id": "default-route",
                    "endpoint": "https://runtime.example/v1/chat/completions",
                    "auth_env": "MERIDIAN_EXTENSION_ROUTE_TOKEN"
                }
            ]
        }
    })
}

#[test]
fn extension_validate_accepts_contract_v1_manifest() {
    let harness = Harness::new("validate_ok");
    let manifest_path = harness.home.join("manifests/observability.json");
    write_manifest(&manifest_path, &sample_manifest("observability-pack"));

    let output = harness.json_ok(&[
        "extension",
        "validate",
        "--manifest",
        manifest_path.to_str().expect("manifest str"),
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    assert_eq!(
        output.get("status").and_then(Value::as_str),
        Some("extension_contract_valid")
    );
    assert_eq!(
        output.get("extension_id").and_then(Value::as_str),
        Some("observability-pack")
    );
    assert_eq!(
        output
            .pointer("/governance_guards/requires_warrant")
            .and_then(Value::as_bool),
        Some(true)
    );
}

#[test]
fn extension_validate_rejects_non_agnostic_or_weak_governance_manifest() {
    let harness = Harness::new("validate_fail");
    let manifest_path = harness.home.join("manifests/bad.json");
    let mut bad = sample_manifest("bad-pack");
    bad["provider_config"]["mode"] = Value::String("vendor_locked".to_string());
    bad["permissions"]["governance"]["requires_treasury_gate"] = Value::Bool(false);
    write_manifest(&manifest_path, &bad);

    let stderr = harness.run_fail(&[
        "extension",
        "validate",
        "--manifest",
        manifest_path.to_str().expect("manifest str"),
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        stderr.contains("provider_config.mode must be 'agnostic'"),
        "expected agnostic mode error, got:\n{}",
        stderr
    );
    assert!(
        stderr.contains("permissions.governance.requires_treasury_gate must be true"),
        "expected governance gate error, got:\n{}",
        stderr
    );
}

#[test]
fn extension_install_export_remove_roundtrip_emits_rollback_receipts() {
    let harness = Harness::new("roundtrip");
    let manifest_path = harness.home.join("manifests/ops_pack.json");
    write_manifest(&manifest_path, &sample_manifest("ops-pack"));

    let install = harness.json_ok(&[
        "extension",
        "install",
        "--manifest",
        manifest_path.to_str().expect("manifest str"),
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        install.get("status").and_then(Value::as_str),
        Some("extension_installed")
    );
    assert_eq!(install.get("mode").and_then(Value::as_str), Some("created"));
    let install_receipt_path = install
        .get("receipt_path")
        .and_then(Value::as_str)
        .expect("install receipt path");
    let install_receipt: Value = serde_json::from_str(
        &fs::read_to_string(install_receipt_path).expect("read install receipt"),
    )
    .expect("parse install receipt");
    assert_eq!(
        install_receipt
            .pointer("/rollback/action")
            .and_then(Value::as_str),
        Some("remove")
    );

    let exported_path = harness.home.join("exports/ops-pack.json");
    let exported = harness.json_ok(&[
        "extension",
        "export",
        "--extension-id",
        "ops-pack",
        "--out",
        exported_path.to_str().expect("export path"),
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        exported.get("status").and_then(Value::as_str),
        Some("extension_exported")
    );
    let exported_manifest: Value =
        serde_json::from_str(&fs::read_to_string(&exported_path).expect("read exported manifest"))
            .expect("parse exported manifest");
    assert_eq!(
        exported_manifest
            .get("extension_id")
            .and_then(Value::as_str),
        Some("ops-pack")
    );

    let removed = harness.json_ok(&[
        "extension",
        "remove",
        "--extension-id",
        "ops-pack",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        removed.get("status").and_then(Value::as_str),
        Some("extension_removed")
    );
    let remove_receipt_path = removed
        .get("receipt_path")
        .and_then(Value::as_str)
        .expect("remove receipt path");
    let remove_receipt: Value = serde_json::from_str(
        &fs::read_to_string(remove_receipt_path).expect("read remove receipt"),
    )
    .expect("parse remove receipt");
    assert_eq!(
        remove_receipt
            .pointer("/rollback/action")
            .and_then(Value::as_str),
        Some("reinstall_from_backup")
    );
    let rollback_manifest = remove_receipt
        .pointer("/rollback/restore_manifest_path")
        .and_then(Value::as_str)
        .expect("rollback restore path")
        .to_string();
    assert!(
        Path::new(&rollback_manifest).exists(),
        "rollback restore manifest should exist: {}",
        rollback_manifest
    );

    let reinstall = harness.json_ok(&[
        "extension",
        "install",
        "--manifest",
        rollback_manifest.as_str(),
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        reinstall.get("status").and_then(Value::as_str),
        Some("extension_installed")
    );
    assert_eq!(
        reinstall.get("extension_id").and_then(Value::as_str),
        Some("ops-pack")
    );
}
