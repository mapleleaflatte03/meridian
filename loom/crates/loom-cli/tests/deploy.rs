use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_deploy_{}_{}_{}",
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
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"deploy fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
    )
    .expect("write runtimes");
    fs::write(
        kernel_dir.join("agent_registry.py"),
        "import json\nprint(json.dumps({'id': 'agent_main', 'name': 'Leviathann', 'org_id': 'org_demo', 'role': 'manager', 'economy_key': 'main', 'approval_required': False, 'budget': {'max_per_run_usd': 1.0}, 'runtime_binding': {'runtime_id': 'loom_native', 'runtime_label': 'Loom Native Runtime', 'bound_org_id': 'org_demo', 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
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
fn deploy_host_is_idempotent_for_same_target_version() {
    let harness = Harness::new("host_idempotent");
    let first = harness.json_ok(&[
        "deploy",
        "host",
        "--root",
        harness.root_str(),
        "--target-version",
        "v1",
        "--format",
        "json",
    ]);
    assert_eq!(
        first.get("status").and_then(Value::as_str),
        Some("deploy_host_applied")
    );
    assert_eq!(
        first.get("idempotent").and_then(Value::as_bool),
        Some(false)
    );

    let second = harness.json_ok(&[
        "deploy",
        "host",
        "--root",
        harness.root_str(),
        "--target-version",
        "v1",
        "--format",
        "json",
    ]);
    assert_eq!(
        second.get("status").and_then(Value::as_str),
        Some("deploy_host_idempotent")
    );
    assert_eq!(
        second.get("idempotent").and_then(Value::as_bool),
        Some(true)
    );
}

#[test]
fn deploy_verify_reports_ok_after_host_apply() {
    let harness = Harness::new("verify_ok");
    harness.run_ok(&[
        "deploy",
        "host",
        "--root",
        harness.root_str(),
        "--target-version",
        "v1",
        "--format",
        "json",
    ]);
    let verify = harness.json_ok(&[
        "deploy",
        "verify",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        verify.get("status").and_then(Value::as_str),
        Some("deploy_verify_ok")
    );
    assert_eq!(
        verify.get("current_version").and_then(Value::as_str),
        Some("v1")
    );
    assert_eq!(
        verify
            .pointer("/checks/deploy_state_present")
            .and_then(Value::as_bool),
        Some(true)
    );
}

#[test]
fn deploy_rollback_restores_previous_version() {
    let harness = Harness::new("rollback");
    harness.run_ok(&[
        "deploy",
        "host",
        "--root",
        harness.root_str(),
        "--target-version",
        "v1",
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "deploy",
        "host",
        "--root",
        harness.root_str(),
        "--target-version",
        "v2",
        "--format",
        "json",
    ]);
    let rollback = harness.json_ok(&[
        "deploy",
        "rollback",
        "--root",
        harness.root_str(),
        "--to-version",
        "v1",
        "--format",
        "json",
    ]);
    assert_eq!(
        rollback.get("status").and_then(Value::as_str),
        Some("deploy_rollback_applied")
    );
    assert_eq!(
        rollback.get("current_version").and_then(Value::as_str),
        Some("v1")
    );
    assert_eq!(
        rollback.get("idempotent").and_then(Value::as_bool),
        Some(false)
    );

    let rollback_again = harness.json_ok(&[
        "deploy",
        "rollback",
        "--root",
        harness.root_str(),
        "--to-version",
        "v1",
        "--format",
        "json",
    ]);
    assert_eq!(
        rollback_again.get("status").and_then(Value::as_str),
        Some("deploy_rollback_idempotent")
    );
    assert_eq!(
        rollback_again
            .get("current_version")
            .and_then(Value::as_str),
        Some("v1")
    );
    assert_eq!(
        rollback_again.get("idempotent").and_then(Value::as_bool),
        Some(true)
    );
}
