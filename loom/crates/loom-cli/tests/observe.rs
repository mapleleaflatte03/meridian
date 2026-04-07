use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_observe_{}_{}_{}",
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
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"observe fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
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
}

#[test]
fn observe_summary_flags_missing_proof_chain_and_includes_fix_hints() {
    let harness = Harness::new("missing_proof");
    let payload = harness.json_ok(&[
        "observe",
        "summary",
        "--root",
        harness.root_str(),
        "--format",
        "json",
        "--fix-hints",
    ]);
    assert_eq!(
        payload.get("status").and_then(Value::as_str),
        Some("observe_summary")
    );
    assert_eq!(
        payload.get("contract_version").and_then(Value::as_str),
        Some("observability_contract_v1")
    );
    assert_eq!(
        payload
            .pointer("/components/proof_chain/status")
            .and_then(Value::as_str),
        Some("missing")
    );
    let alerts = payload
        .get("alerts")
        .and_then(Value::as_array)
        .expect("alerts array");
    assert!(alerts
        .iter()
        .filter_map(|item| item.get("code").and_then(Value::as_str))
        .any(|code| code == "proof_chain_missing"));
    assert!(payload
        .get("fix_hints")
        .and_then(Value::as_array)
        .map(|items| !items.is_empty())
        .unwrap_or(false));
}

#[test]
fn observe_summary_marks_proof_chain_ready_when_artifacts_exist() {
    let harness = Harness::new("proof_ready");
    let artifacts_root = harness.root.join("artifacts");
    fs::create_dir_all(artifacts_root.join("zk")).expect("zk dir");
    fs::create_dir_all(artifacts_root.join("settlement")).expect("settlement dir");
    fs::write(
        artifacts_root.join("zk/latest.json"),
        "{\n  \"status\": \"zk_proof_prepared\",\n  \"proof_backend\": \"sp1\",\n  \"verification\": \"verified\"\n}\n",
    )
    .expect("write zk latest");
    fs::write(
        artifacts_root.join("settlement/latest.json"),
        "{\n  \"status\": \"zk_settlement_captured\",\n  \"reservation_id\": \"resv_123\"\n}\n",
    )
    .expect("write settlement latest");

    let payload = harness.json_ok(&[
        "observe",
        "summary",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        payload
            .pointer("/components/proof_chain/status")
            .and_then(Value::as_str),
        Some("ready")
    );
    assert_eq!(
        payload
            .pointer("/components/proof_chain/zk_status")
            .and_then(Value::as_str),
        Some("zk_proof_prepared")
    );
    assert_eq!(
        payload
            .pointer("/components/proof_chain/settlement_status")
            .and_then(Value::as_str),
        Some("zk_settlement_captured")
    );
}

#[test]
fn observe_alerts_returns_compact_alert_view() {
    let harness = Harness::new("alerts_view");
    let payload = harness.json_ok(&[
        "observe",
        "alerts",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        payload.get("status").and_then(Value::as_str),
        Some("observe_alerts")
    );
    assert_eq!(
        payload.get("contract_version").and_then(Value::as_str),
        Some("observability_contract_v1")
    );
    assert!(payload.get("alerts").and_then(Value::as_array).is_some());
}

#[test]
fn observe_summary_surfaces_connect_degraded_alerts_and_fix_hints() {
    let harness = Harness::new("connect_degraded");
    harness.run_ok(&[
        "connect",
        "scaffold",
        "--name",
        "telegram_observe_adapter",
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
        "telegram-observe-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-observe-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let registry_path = harness.root.join("state/connect/registry.json");
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
            item.get("adapter_id").and_then(Value::as_str) == Some("telegram-observe-adapter")
        })
        .expect("telegram adapter");
    adapter["action_schema"] = Value::String(String::new());
    fs::write(
        &registry_path,
        serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
    .expect("write registry");

    let fail_output = harness.run_fail(&[
        "connect",
        "test",
        "--adapter-id",
        "telegram-observe-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert!(
        fail_output.contains("missing_action_schema"),
        "expected degraded connect test failure, got:\n{}",
        fail_output
    );
    harness.run_ok(&[
        "connect",
        "health",
        "--adapter-id",
        "telegram-observe-adapter",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);

    let payload = harness.json_ok(&[
        "observe",
        "summary",
        "--root",
        harness.root_str(),
        "--format",
        "json",
        "--fix-hints",
    ]);
    assert_eq!(
        payload
            .pointer("/components/connect/status")
            .and_then(Value::as_str),
        Some("degraded")
    );
    assert_eq!(
        payload
            .pointer("/components/connect/degraded_adapters")
            .and_then(Value::as_u64),
        Some(1)
    );
    let alert_codes = payload
        .get("alerts")
        .and_then(Value::as_array)
        .expect("alerts")
        .iter()
        .filter_map(|item| item.get("code").and_then(Value::as_str))
        .collect::<Vec<_>>();
    assert!(alert_codes.contains(&"connect_degraded"));
    assert!(alert_codes.contains(&"connect_fallback_active"));

    let fix_codes = payload
        .get("fix_hints")
        .and_then(Value::as_array)
        .expect("fix_hints")
        .iter()
        .filter_map(|item| item.get("code").and_then(Value::as_str))
        .collect::<Vec<_>>();
    assert!(fix_codes.contains(&"connect_degraded"));
}

#[test]
fn observe_watch_stream_emits_realtime_frames_and_persists_alert_stream() {
    let harness = Harness::new("watch_stream");
    let output = harness.run_ok(&[
        "observe",
        "watch",
        "--root",
        harness.root_str(),
        "--format",
        "json",
        "--stream",
        "--iterations",
        "2",
        "--interval-seconds",
        "0",
        "--fix-hints",
    ]);
    let lines = output
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect::<Vec<_>>();
    assert_eq!(
        lines.len(),
        3,
        "expected 2 frame lines + 1 completion line, got:\n{}",
        output
    );

    for (index, line) in lines.iter().take(2).enumerate() {
        let value: Value = serde_json::from_str(line).expect("parse frame json");
        assert_eq!(
            value.get("status").and_then(Value::as_str),
            Some("observe_watch_frame")
        );
        assert_eq!(
            value.get("iteration").and_then(Value::as_u64),
            Some((index + 1) as u64)
        );
        assert!(
            value
                .get("alert_count")
                .and_then(Value::as_u64)
                .unwrap_or_default()
                >= 1,
            "expected alert_count >= 1 for frame {}",
            index + 1
        );
    }

    let completion: Value = serde_json::from_str(lines.get(2).copied().expect("completion line"))
        .expect("parse completion json");
    assert_eq!(
        completion.get("status").and_then(Value::as_str),
        Some("observe_watch_complete")
    );
    assert_eq!(
        completion.get("emitted_frames").and_then(Value::as_u64),
        Some(2)
    );

    let stream_path = harness.root.join("state/observability/alerts_stream.jsonl");
    let stream_raw = fs::read_to_string(&stream_path).expect("read stream artifact");
    let stream_lines = stream_raw
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect::<Vec<_>>();
    assert_eq!(stream_lines.len(), 2, "expected two stream frame entries");
    for line in stream_lines {
        let value: Value = serde_json::from_str(line).expect("parse stream frame json");
        assert_eq!(
            value.get("status").and_then(Value::as_str),
            Some("observe_watch_frame")
        );
    }
}
