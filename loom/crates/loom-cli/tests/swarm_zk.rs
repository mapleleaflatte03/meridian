use ed25519_dalek::{Signature, Signer, SigningKey};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_swarm_zk_{}_{}_{}",
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
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"swarm zk fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
    )
    .expect("write runtimes");
    fs::write(
        kernel_dir.join("agent_registry.py"),
        "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'Atlas', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 1.0}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
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
        "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n\ndef reserve_runtime_budget(agent_id, estimated_cost, org_id=None, action='', resource='', context=None, policy_ref=''):\n    return {'allowed': True, 'reservation_id': 'bud_swarm', 'reason': 'ok'}\n\ndef commit_runtime_budget(reservation_id, actual_cost_usd, note=''):\n    return {'reservation_id': reservation_id, 'status': 'committed', 'commit_reason': note}\n\ndef release_runtime_budget(reservation_id, reason=''):\n    return {'reservation_id': reservation_id, 'status': 'released', 'release_reason': reason}\n",
    )
    .expect("write treasury");
}

fn epoch_ms_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn warrant_message(id: [u8; 32], scope_cbor: &[u8], expiry_epoch_ms: u64) -> Vec<u8> {
    let scope_hash: [u8; 32] = Sha256::digest(scope_cbor).into();
    let mut message = Vec::with_capacity(32 + 32 + 8);
    message.extend_from_slice(&id);
    message.extend_from_slice(&scope_hash);
    message.extend_from_slice(&expiry_epoch_ms.to_be_bytes());
    message
}

fn write_signed_warrant(path: &Path) {
    let signer = SigningKey::from_bytes(&[17u8; 32]);
    let mut id = [0u8; 32];
    for (index, slot) in id.iter_mut().enumerate() {
        *slot = (index as u8).wrapping_mul(9).wrapping_add(1);
    }
    let scope_cbor = vec![0xA1, 0x65, b's', b'w', b'a', b'r', b'm', 0xF5];
    let expiry_epoch_ms = epoch_ms_now() + 60_000;
    let signature: Signature = signer.sign(&warrant_message(id, &scope_cbor, expiry_epoch_ms));
    let payload = json!({
        "id_hex": hex::encode(id),
        "scope_cbor_hex": hex::encode(scope_cbor),
        "expiry_epoch_ms": expiry_epoch_ms,
        "kernel_sig_hex": hex::encode(signature.to_bytes()),
        "kernel_pub_hex": hex::encode(signer.verifying_key().to_bytes()),
    });
    fs::write(
        path,
        serde_json::to_string_pretty(&payload).expect("warrant json"),
    )
    .expect("write warrant");
}

#[test]
fn swarm_run_settle_zk_one_command_lane() {
    let harness = Harness::new("swarm_zk_lane");
    let warrant_path = harness.home.join("swarm-warrant.json");
    write_signed_warrant(&warrant_path);

    let output = harness.json_ok(&[
        "swarm",
        "run",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "research",
        "--resource",
        "system_info",
        "--module",
        "builtin:system.info",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--estimated-cost-usd",
        "0.05",
        "--actual-cost-usd",
        "0.05",
        "--settle-zk",
        "--zk-backend",
        "sp1",
        "--format",
        "json",
    ]);

    assert_eq!(
        output.get("status").and_then(Value::as_str),
        Some("swarm_run_settled")
    );
    assert_eq!(
        output.get("proof_backend").and_then(Value::as_str),
        Some("sp1")
    );
    assert_eq!(
        output.get("settlement_status").and_then(Value::as_str),
        Some("prepared")
    );
    assert_eq!(
        output.get("treasury_status").and_then(Value::as_str),
        Some("committed")
    );
    assert!(harness.root.join("artifacts/zk/latest.json").exists());
    assert!(harness
        .root
        .join("artifacts/settlement/latest.json")
        .exists());
    assert!(harness.root.join("artifacts/swarm/latest.json").exists());
}
