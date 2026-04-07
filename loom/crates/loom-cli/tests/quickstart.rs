use serde_json::Value;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);
static GLOBAL_QUICKSTART_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn quickstart_test_lock() -> &'static Mutex<()> {
    GLOBAL_QUICKSTART_LOCK.get_or_init(|| Mutex::new(()))
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_quickstart_{}_{}_{}",
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
        copy_kernel_fixture(&kernel);
        Self { home, root, kernel }
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
fn quickstart_noninteractive_lane_generates_first_proof_artifacts() {
    let _guard = quickstart_test_lock().lock().expect("quickstart lock");
    let harness = Harness::new("noninteractive");
    let args = [
        "quickstart",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--org-id",
        "org_quickstart",
        "--charter",
        "Quickstart Nation Charter",
        "--agent-name",
        "Quickstart Agent",
        "--webhook-url",
        "https://example.com/quickstart-hook",
        "--channel-test-text",
        "quickstart lane ping",
        "--format",
        "json",
    ];
    let output = harness.run_output(&args);
    assert_success(&args, &output);
    let payload: Value = serde_json::from_slice(&output.stdout).expect("parse quickstart json");
    assert_eq!(
        payload.get("status").and_then(Value::as_str),
        Some("quickstart_completed")
    );
    let execution_path = payload
        .pointer("/artifacts/execution_path")
        .and_then(Value::as_str)
        .expect("execution_path");
    let parity_report_path = payload
        .pointer("/artifacts/parity_report_path")
        .and_then(Value::as_str)
        .expect("parity_report_path");
    let shadow_latest_path = payload
        .pointer("/artifacts/shadow_latest_path")
        .and_then(Value::as_str)
        .expect("shadow_latest_path");
    assert!(
        Path::new(execution_path).exists(),
        "execution artifact missing"
    );
    assert!(
        Path::new(parity_report_path).exists(),
        "parity report artifact missing"
    );
    assert!(
        Path::new(shadow_latest_path).exists(),
        "shadow latest artifact missing"
    );
}

#[test]
fn quickstart_interactive_mode_emits_progress_bar() {
    let _guard = quickstart_test_lock().lock().expect("quickstart lock");
    let harness = Harness::new("interactive");
    let mut command = harness.base_command();
    command.args([
        "quickstart",
        "--interactive",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
    ]);
    command.stdin(Stdio::piped());
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());
    let mut child = command.spawn().expect("spawn quickstart interactive");
    let scripted_answers = "\nInteractive Charter\nInteractive Agent\nhttps://example.com/interactive-hook\ninteractive ping\n";
    child
        .stdin
        .as_mut()
        .expect("stdin")
        .write_all(scripted_answers.as_bytes())
        .expect("write answers");
    let output = child.wait_with_output().expect("wait quickstart");
    assert!(
        output.status.success(),
        "interactive quickstart failed\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        stdout.contains("Meridian Loom // QUICKSTART"),
        "missing quickstart banner\n{}",
        stdout
    );
    assert!(
        stdout.contains("[") && stdout.contains("]") && stdout.contains("step"),
        "missing progress output\n{}",
        stdout
    );
}
