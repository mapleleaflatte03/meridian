use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir =
        std::env::temp_dir().join(format!("loom_auth_{}_{}_{}", label, std::process::id(), n));
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
    let adapters_dir = kernel_dir.join("adapters");
    fs::create_dir_all(&adapters_dir).expect("adapters dir");
    fs::write(
        kernel_dir.join("runtimes.json"),
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"auth fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
    )
    .expect("write runtimes");
    fs::write(
        kernel_dir.join("agent_registry.py"),
        "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': agent_id.title(), 'org_id': org_id, 'role': 'operator', 'economy_key': 'main', 'approval_required': False, 'budget': {'max_per_run_usd': 2.0}, 'runtime_binding': {'runtime_id': 'loom_native', 'runtime_label': 'Loom Native Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
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
    fs::write(
        kernel_dir.join("treasury.py"),
        "def check_budget(agent_id, estimated_cost, org_id=None):\n    return True, 'ok'\n",
    )
    .expect("write treasury");
    fs::write(adapters_dir.join("__init__.py"), "").expect("write adapters init");
    fs::write(
        adapters_dir.join("meridian_compatible.py"),
        r#"from authority import check_authority
from court import get_restrictions
from treasury import check_budget

def pre_action_check(org_id, envelope):
    restrictions = get_restrictions(envelope.get('agent_id'), org_id=org_id) or []
    if 'execute' in restrictions or 'remediation_only' in restrictions:
        return {
            'allowed': False,
            'reason': 'restricted',
            'stage': 'sanction_controls',
            'restrictions': restrictions,
        }
    allowed, reason = check_authority(envelope.get('agent_id'), envelope.get('action_type'), org_id=org_id)
    if not allowed:
        return {
            'allowed': False,
            'reason': reason,
            'stage': 'approval_hook',
            'restrictions': restrictions,
        }
    estimated_cost = float(envelope.get('estimated_cost_usd', 0.0) or 0.0)
    if estimated_cost > 0:
        allowed, reason = check_budget(envelope.get('agent_id'), estimated_cost, org_id=org_id)
        if not allowed:
            return {
                'allowed': False,
                'reason': reason,
                'stage': 'budget_gate',
                'restrictions': restrictions,
            }
    return {'allowed': True, 'reason': 'ok', 'stage': 'ok', 'restrictions': restrictions}
"#,
    )
    .expect("write adapter");
}

#[test]
fn auth_status_scaffolds_auth_contract_and_aliases() {
    let harness = Harness::new("status_scaffold");
    let payload = harness.json_ok(&[
        "auth",
        "status",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        payload.get("status").and_then(Value::as_str),
        Some("auth_status")
    );
    assert_eq!(
        payload.get("contract_version").and_then(Value::as_str),
        Some("auth_contract_v1")
    );
    assert!(
        payload
            .get("profile_count")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            >= 1
    );
    assert!(
        payload
            .get("alias_count")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            >= 1
    );
    let aliases = payload
        .get("aliases")
        .and_then(Value::as_array)
        .expect("aliases array");
    assert!(aliases.iter().any(|entry| {
        entry
            .get("alias")
            .and_then(Value::as_str)
            .map(|alias| alias.starts_with("profile."))
            .unwrap_or(false)
    }));
}

#[test]
fn auth_rotate_and_revoke_record_audit_with_governance() {
    let harness = Harness::new("rotate_revoke");
    let rotate = harness.json_ok(&[
        "auth",
        "rotate",
        "--alias",
        "manager_primary",
        "--env-var",
        "MERIDIAN_MANAGER_TOKEN_A",
        "--agent-id",
        "agent_main",
        "--kernel-path",
        harness.kernel_str(),
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        rotate.get("status").and_then(Value::as_str),
        Some("auth_rotated")
    );
    assert_eq!(
        rotate
            .pointer("/governance/allowed")
            .and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        rotate
            .pointer("/governance/sanction_gate_decision")
            .and_then(Value::as_str),
        Some("allow")
    );

    let revoke = harness.json_ok(&[
        "auth",
        "revoke",
        "--alias",
        "manager_primary",
        "--agent-id",
        "agent_main",
        "--kernel-path",
        harness.kernel_str(),
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        revoke.get("status").and_then(Value::as_str),
        Some("auth_revoked")
    );
    assert_eq!(
        revoke.pointer("/alias/status").and_then(Value::as_str),
        Some("revoked")
    );

    let audit = harness.json_ok(&[
        "auth",
        "audit",
        "--root",
        harness.root_str(),
        "--format",
        "json",
        "--limit",
        "20",
    ]);
    let events = audit
        .get("events")
        .and_then(Value::as_array)
        .expect("events array");
    assert!(events.len() >= 2);
    let action_types = events
        .iter()
        .filter_map(|event| event.get("action_type").and_then(Value::as_str))
        .collect::<Vec<_>>();
    assert!(action_types.iter().any(|value| *value == "auth.rotate"));
    assert!(action_types.iter().any(|value| *value == "auth.revoke"));
}

#[test]
fn auth_rotate_fails_when_governance_denies_action() {
    let harness = Harness::new("rotate_denied");
    let authority_path = harness.kernel.join("kernel/authority.py");
    fs::write(
        authority_path,
        "def check_authority(agent_id, action, org_id=None):\n    if action == 'auth.rotate':\n        return False, 'blocked by authority policy'\n    return True, 'ok'\n",
    )
    .expect("overwrite authority");

    let output = harness.run_fail(&[
        "auth",
        "rotate",
        "--alias",
        "manager_primary",
        "--env-var",
        "MERIDIAN_MANAGER_TOKEN_A",
        "--agent-id",
        "agent_main",
        "--kernel-path",
        harness.kernel_str(),
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(output.contains("blocked by authority policy"));
}
