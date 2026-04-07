use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_personal_agent_supervision_{}_{}_{}",
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
    slug: String,
}

impl Harness {
    fn new(label: &str) -> Self {
        Self::new_with_channel(label, true)
    }

    fn new_without_channel(label: &str) -> Self {
        Self::new_with_channel(label, false)
    }

    fn new_with_channel(label: &str, connect_channel: bool) -> Self {
        let home = unique_temp_dir(label);
        let root = home.join(".local/share/meridian-loom/runtime/default");
        let kernel = home.join("kernel");
        copy_kernel_fixture(&kernel);
        let harness = Self {
            home,
            root,
            kernel,
            slug: "smoke-agent".to_string(),
        };
        harness.run_ok(&[
            "init",
            "--mode",
            "embedded",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--org-id",
            "local_foundry",
        ]);
        harness.run_ok(&[
            "new-agent",
            "--name",
            "Smoke Agent",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--org-id",
            "local_foundry",
            "--format",
            "json",
        ]);
        if connect_channel {
            harness.run_ok(&[
                "channel",
                "connect",
                "webhook",
                "--root",
                harness.root_str(),
                "--agent",
                &harness.slug,
                "--url",
                "https://example.com/hook",
            ]);
        }
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

    fn log_path(&self) -> PathBuf {
        self.root
            .join("run")
            .join("personal-agents")
            .join(format!("{}.log", self.slug))
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

    fn run_output_with_env(&self, args: &[&str], envs: &[(&str, &str)]) -> Output {
        let mut command = self.base_command();
        command.args(args);
        for (key, value) in envs {
            command.env(key, value);
        }
        command.output().expect("run loom command with env")
    }

    fn run_ok(&self, args: &[&str]) -> String {
        let output = self.run_output(args);
        assert_success(args, &output);
        String::from_utf8_lossy(&output.stdout).to_string()
    }

    fn run_ok_with_env(&self, args: &[&str], envs: &[(&str, &str)]) -> String {
        let output = self.run_output_with_env(args, envs);
        assert_success(args, &output);
        String::from_utf8_lossy(&output.stdout).to_string()
    }

    fn json_ok(&self, args: &[&str]) -> Value {
        let output = self.run_output(args);
        assert_success(args, &output);
        serde_json::from_slice(&output.stdout).expect("parse json output")
    }

    fn status_json(&self) -> Value {
        self.json_ok(&[
            "run-agent",
            "status",
            &self.slug,
            "--root",
            self.root_str(),
            "--format",
            "json",
        ])
    }

    fn inspect_json(&self) -> Value {
        self.json_ok(&[
            "run-agent",
            "inspect",
            &self.slug,
            "--root",
            self.root_str(),
            "--history-limit",
            "5",
            "--diagnostic-limit",
            "5",
            "--receipt-limit",
            "5",
            "--delivery-limit",
            "5",
            "--format",
            "json",
        ])
    }

    fn diagnose_json(&self) -> Value {
        self.json_ok(&[
            "run-agent",
            "diagnose",
            &self.slug,
            "--root",
            self.root_str(),
            "--history-limit",
            "5",
            "--diagnostic-limit",
            "5",
            "--receipt-limit",
            "5",
            "--delivery-limit",
            "5",
            "--format",
            "json",
        ])
    }

    fn watch_json_once(&self) -> Value {
        self.json_ok(&[
            "run-agent",
            "watch",
            &self.slug,
            "--root",
            self.root_str(),
            "--once",
            "--history-limit",
            "5",
            "--diagnostic-limit",
            "5",
            "--receipt-limit",
            "5",
            "--delivery-limit",
            "5",
            "--format",
            "json",
        ])
    }

    fn stop_json(&self) -> Value {
        self.json_ok(&[
            "run-agent",
            "stop",
            &self.slug,
            "--root",
            self.root_str(),
            "--format",
            "json",
        ])
    }

    fn wait_for_status<F>(&self, timeout: Duration, predicate: F) -> Value
    where
        F: Fn(&Value) -> bool,
    {
        let deadline = Instant::now() + timeout;
        loop {
            let status = self.status_json();
            if predicate(&status) {
                return status;
            }
            if Instant::now() >= deadline {
                panic!(
                    "timed out waiting for status predicate. last status={}",
                    serde_json::to_string_pretty(&status).unwrap_or_default()
                );
            }
            thread::sleep(Duration::from_millis(200));
        }
    }
}

impl Drop for Harness {
    fn drop(&mut self) {
        let _ = self.run_output(&[
            "run-agent",
            "stop",
            &self.slug,
            "--root",
            self.root_str(),
            "--format",
            "json",
        ]);
        thread::sleep(Duration::from_millis(800));
        let _ = fs::remove_dir_all(&self.home);
    }
}

fn assert_success(args: &[&str], output: &Output) {
    assert!(
        output.status.success(),
        "command failed: loom {}\nstdout:\n{}\nstderr:\n{}",
        args.join(" "),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn kernel_fixture_source() -> PathBuf {
    if let Ok(value) = std::env::var("MERIDIAN_TEST_KERNEL_PATH") {
        let candidate = PathBuf::from(value.trim());
        if candidate.join("kernel").join("agent_registry.py").exists() {
            return candidate;
        }
    }
    for candidate in ["/opt/meridian-kernel", "/tmp/meridian-kernel"] {
        let path = PathBuf::from(candidate);
        if path.join("kernel").join("agent_registry.py").exists() {
            return path;
        }
    }
    panic!(
        "kernel fixture source not found; set MERIDIAN_TEST_KERNEL_PATH to a Meridian Kernel checkout"
    );
}

fn copy_kernel_fixture(destination: &Path) {
    fs::create_dir_all(destination).expect("create kernel destination");
    let source = kernel_fixture_source();
    let status = Command::new("cp")
        .args([
            "-R",
            source.join(".").to_str().expect("source str"),
            destination.to_str().expect("dest str"),
        ])
        .status()
        .expect("copy kernel fixture");
    assert!(status.success(), "cp -R {} failed", source.display());
    let agent_registry = destination.join("kernel").join("agent_registry.json");
    // /opt fixture may contain a symlink into a live workspace registry.
    // Detach it so supervision tests never mutate shared state or race each other.
    if let Ok(metadata) = fs::symlink_metadata(&agent_registry) {
        if metadata.file_type().is_symlink() {
            fs::remove_file(&agent_registry).expect("remove copied symlinked agent registry");
        }
    }
    fs::write(
        &agent_registry,
        "{\n  \"agents\": {},\n  \"updatedAt\": \"1970-01-01T00:00:00Z\"\n}\n",
    )
    .expect("reset copied kernel agent registry");
    let ledger_path = destination.join("economy").join("ledger.json");
    if !ledger_path.exists() {
        if let Some(parent) = ledger_path.parent() {
            fs::create_dir_all(parent).expect("create economy dir");
        }
        fs::write(
            &ledger_path,
            "{\n  \"version\": 1,\n  \"schema\": \"meridian-kernel-economy-v1\",\n  \"updatedAt\": \"1970-01-01T00:00:00Z\",\n  \"agents\": {},\n  \"treasury\": {\n    \"cash_usd\": 0.0,\n    \"reserve_floor_usd\": 50.0,\n    \"total_revenue_usd\": 0.0,\n    \"support_received_usd\": 0.0,\n    \"owner_capital_contributed_usd\": 0.0,\n    \"expenses_recorded_usd\": 0.0,\n    \"owner_draws_usd\": 0.0\n  },\n  \"bonus_pool\": {\"available_usd\": 0.0},\n  \"epoch\": {\n    \"number\": 0,\n    \"started_at\": \"1970-01-01T00:00:00Z\",\n    \"auth_decay_per_epoch\": 5\n  },\n  \"transactions\": []\n}\n",
        )
        .expect("seed kernel ledger fixture");
    }
}

#[test]
fn manual_policy_exposes_crash_and_requires_operator_restart() {
    let harness = Harness::new("manual_policy");
    harness.run_ok_with_env(
        &[
            "run-agent",
            &harness.slug,
            "--root",
            harness.root_str(),
            "--restart-policy",
            "manual",
            "--restart-backoff-seconds",
            "1",
            "--poll-seconds",
            "1",
        ],
        &[("MERIDIAN_LOOM_AGENT_CHAOS", "after_tick:once:91")],
    );

    let status = harness.wait_for_status(Duration::from_secs(12), |value| {
        value["supervision_action"].as_str() == Some("manual_restart_required")
    });
    assert_eq!(status["status"].as_str(), Some("crashed"));
    assert_eq!(
        status["crash_state"].as_str(),
        Some("manual_restart_required")
    );
    assert_eq!(status["worker_running"].as_bool(), Some(false));
    assert_eq!(status["supervisor_running"].as_bool(), Some(false));
    assert!(status["last_crash_reason"]
        .as_str()
        .unwrap_or_default()
        .contains("91"));

    let inspect = harness.inspect_json();
    let alerts = inspect["alerts"].as_array().cloned().unwrap_or_default();
    assert!(alerts.iter().any(|item| {
        item.as_str()
            .unwrap_or_default()
            .contains("operator restart required")
    }));
    let diagnose = harness.diagnose_json();
    assert_eq!(
        diagnose["diagnosis"]["status"].as_str(),
        Some("worker_crashed_manual_policy")
    );
    let recommended_actions = diagnose["recommended_actions"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    assert!(recommended_actions.iter().any(|item| {
        item["command"]
            .as_str()
            .unwrap_or_default()
            .contains("loom run-agent reconcile smoke-agent")
    }));

    let log = fs::read_to_string(harness.log_path()).expect("read supervisor log");
    assert!(log.contains("chaos injected phase=after_tick mode=once exit_code=91"));
    assert!(log.contains("worker exit unexpected=true reason=worker exited with code 91"));
}

#[test]
fn always_policy_recovers_after_single_injected_crash() {
    let harness = Harness::new("always_once");
    harness.run_ok_with_env(
        &[
            "run-agent",
            &harness.slug,
            "--root",
            harness.root_str(),
            "--restart-policy",
            "always",
            "--restart-backoff-seconds",
            "1",
            "--poll-seconds",
            "1",
        ],
        &[("MERIDIAN_LOOM_AGENT_CHAOS", "after_tick:once:92")],
    );

    let status = harness.wait_for_status(Duration::from_secs(16), |value| {
        value["supervision_action"].as_str() == Some("healthy")
            && value["worker_running"].as_bool() == Some(true)
            && value["supervisor_running"].as_bool() == Some(true)
            && value["last_crash_reason"]
                .as_str()
                .unwrap_or_default()
                .contains("92")
    });
    assert_eq!(status["crash_state"].as_str(), Some("recovered"));

    let inspect = harness.inspect_json();
    assert_eq!(inspect["agent"]["status"].as_str(), Some("running"));
    assert_eq!(
        inspect["agent"]["supervision_action"].as_str(),
        Some("healthy")
    );
    let diagnose = harness.diagnose_json();
    assert_eq!(diagnose["diagnosis"]["status"].as_str(), Some("healthy"));
    assert!(inspect["recent_memory_receipts"]
        .as_array()
        .map(|items| !items.is_empty())
        .unwrap_or(false));

    let log = fs::read_to_string(harness.log_path()).expect("read supervisor log");
    assert!(log.contains("worker exit unexpected=true reason=worker exited with code 92"));
    assert!(log.contains("worker spawned pid="));

    let stop = harness.stop_json();
    assert!(matches!(
        stop["status"].as_str(),
        Some("stop_requested") | Some("stop_written_no_process")
    ));
}

#[test]
fn always_policy_surfaces_waiting_backoff_during_repeated_crashes() {
    let harness = Harness::new("always_backoff");
    harness.run_ok_with_env(
        &[
            "run-agent",
            &harness.slug,
            "--root",
            harness.root_str(),
            "--restart-policy",
            "always",
            "--restart-backoff-seconds",
            "5",
            "--poll-seconds",
            "1",
        ],
        &[("MERIDIAN_LOOM_AGENT_CHAOS", "after_tick:always:93")],
    );

    let status = harness.wait_for_status(Duration::from_secs(12), |value| {
        value["supervision_action"].as_str() == Some("waiting_backoff")
            && value["supervisor_running"].as_bool() == Some(true)
            && value["worker_running"].as_bool() == Some(false)
    });
    assert_eq!(status["crash_state"].as_str(), Some("awaiting_restart"));
    assert!(
        status["next_restart_after_unix_ms"]
            .as_u64()
            .unwrap_or_default()
            > status["last_crash_unix_ms"].as_u64().unwrap_or_default()
    );

    let watch = harness.watch_json_once();
    assert_eq!(
        watch["agent"]["supervision_action"].as_str(),
        Some("waiting_backoff")
    );
    let alerts = watch["alerts"].as_array().cloned().unwrap_or_default();
    assert!(alerts.iter().any(|item| {
        item.as_str()
            .unwrap_or_default()
            .contains("waiting for restart backoff")
    }));
    let diagnose = harness.diagnose_json();
    assert_eq!(
        diagnose["diagnosis"]["status"].as_str(),
        Some("restart_backoff_active")
    );
    let recommended_actions = diagnose["recommended_actions"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    assert!(recommended_actions.iter().any(|item| {
        item["command"]
            .as_str()
            .unwrap_or_default()
            .contains("loom run-agent watch smoke-agent")
    }));

    let stop = harness.stop_json();
    assert!(matches!(
        stop["status"].as_str(),
        Some("stop_requested") | Some("stop_written_no_process")
    ));
}

#[test]
fn diagnose_surfaces_missing_channel_remediation_for_running_agent() {
    let harness = Harness::new_without_channel("no_channel");
    harness.run_ok(&[
        "run-agent",
        &harness.slug,
        "--root",
        harness.root_str(),
        "--restart-policy",
        "always",
        "--restart-backoff-seconds",
        "1",
        "--poll-seconds",
        "1",
    ]);

    let _status = harness.wait_for_status(Duration::from_secs(12), |value| {
        value["worker_running"].as_bool() == Some(true)
            && value["supervisor_running"].as_bool() == Some(true)
    });
    let diagnose = harness.diagnose_json();
    assert_eq!(
        diagnose["diagnosis"]["status"].as_str(),
        Some("no_delivery_channel")
    );
    let recommended_actions = diagnose["recommended_actions"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    assert!(recommended_actions.iter().any(|item| {
        item["command"]
            .as_str()
            .unwrap_or_default()
            .contains("loom channel connect webhook --agent smoke-agent")
    }));
}
