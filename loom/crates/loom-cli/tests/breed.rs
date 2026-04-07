use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir =
        std::env::temp_dir().join(format!("loom_breed_{}_{}_{}", label, std::process::id(), n));
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
    fn new(label: &str, blocked_by_court: bool, denied_by_authority: bool) -> Self {
        let home = unique_temp_dir(label);
        let root = home.join(".local/share/meridian-loom/runtime/default");
        let kernel = home.join("kernel");
        scaffold_kernel_fixture(&kernel, blocked_by_court, denied_by_authority);
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

fn scaffold_kernel_fixture(root: &Path, blocked_by_court: bool, denied_by_authority: bool) {
    let kernel_dir = root.join("kernel");
    fs::create_dir_all(&kernel_dir).expect("kernel dir");
    fs::write(
        kernel_dir.join("runtimes.json"),
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"breed fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
    )
    .expect("write runtimes");

    fs::write(
        kernel_dir.join("agent_registry.py"),
        r#"import json, sys

def get_agent(agent_id, org_id=None):
    records = {
        "agent_atlas": {
            "id": "agent_atlas",
            "name": "Atlas",
            "org_id": org_id or "org_demo",
            "role": "analyst",
            "purpose": "Research and analysis",
            "scopes": ["research", "read"],
            "budget": {"max_per_run_usd": 0.5},
            "approval_required": False,
            "runtime_binding": {"runtime_id": "loom_native", "runtime_label": "Loom Native Runtime"}
        },
        "agent_quill": {
            "id": "agent_quill",
            "name": "Quill",
            "org_id": org_id or "org_demo",
            "role": "writer",
            "purpose": "Write and summarize",
            "scopes": ["write", "deliver"],
            "budget": {"max_per_run_usd": 0.4},
            "approval_required": False,
            "runtime_binding": {"runtime_id": "loom_native", "runtime_label": "Loom Native Runtime"}
        }
    }
    return records.get(agent_id)
"#,
    )
    .expect("write registry");

    let restrictions = if blocked_by_court { "['breed']" } else { "[]" };
    fs::write(
        kernel_dir.join("court.py"),
        format!(
            "def get_restrictions(agent_id, org_id=None):\n    return {}\n",
            restrictions
        ),
    )
    .expect("write court");

    let authority_return = if denied_by_authority {
        "False, 'denied in fixture'"
    } else {
        "True, 'ok'"
    };
    fs::write(
        kernel_dir.join("authority.py"),
        format!(
            "def check_authority(agent_id, action, org_id=None):\n    return {}\n",
            authority_return
        ),
    )
    .expect("write authority");
}

#[test]
fn breed_creates_dna_artifact_when_governance_allows() {
    let harness = Harness::new("breed_ok", false, false);
    let output = harness.json_ok(&[
        "breed",
        "agent_atlas",
        "agent_quill",
        "--agent-id",
        "agent_atlas",
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "org_demo",
        "--mutation-rate",
        "0.15",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        output.get("status").and_then(Value::as_str),
        Some("breed_created")
    );
    assert!(output
        .get("dna_id")
        .and_then(Value::as_str)
        .map(|value| !value.is_empty())
        .unwrap_or(false));
    assert!(harness
        .root
        .join("artifacts/evolution/latest.json")
        .exists());
}

#[test]
fn breed_is_deterministic_for_same_inputs() {
    let harness = Harness::new("breed_deterministic", false, false);
    let first = harness.json_ok(&[
        "breed",
        "agent_atlas",
        "agent_quill",
        "--agent-id",
        "agent_atlas",
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "org_demo",
        "--mutation-rate",
        "0.20",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    let second = harness.json_ok(&[
        "breed",
        "agent_atlas",
        "agent_quill",
        "--agent-id",
        "agent_atlas",
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "org_demo",
        "--mutation-rate",
        "0.20",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(first.get("dna_hash"), second.get("dna_hash"));
    assert_eq!(first.get("dna_id"), second.get("dna_id"));
}

#[test]
fn breed_is_blocked_by_court_gate() {
    let harness = Harness::new("breed_court_block", true, false);
    let output = harness.json_ok(&[
        "breed",
        "agent_atlas",
        "agent_quill",
        "--agent-id",
        "agent_atlas",
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "org_demo",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        output.get("status").and_then(Value::as_str),
        Some("breed_blocked")
    );
    assert_eq!(
        output.get("court_status").and_then(Value::as_str),
        Some("blocked")
    );
    assert!(!harness
        .root
        .join("artifacts/evolution/latest.json")
        .exists());
}

#[test]
fn breed_is_blocked_by_authority_gate() {
    let harness = Harness::new("breed_auth_block", false, true);
    let output = harness.json_ok(&[
        "breed",
        "agent_atlas",
        "agent_quill",
        "--agent-id",
        "agent_atlas",
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "org_demo",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        output.get("status").and_then(Value::as_str),
        Some("breed_blocked")
    );
    assert_eq!(
        output.get("authority_status").and_then(Value::as_str),
        Some("denied")
    );
    assert!(!harness
        .root
        .join("artifacts/evolution/latest.json")
        .exists());
}
