use ed25519_dalek::{Signature, Signer, SigningKey};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_embodied_grpc_physical_{}_{}_{}",
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

    fn run_output_with_env(&self, args: &[&str], envs: &[(&str, &str)]) -> Output {
        let mut command = self.base_command();
        for (name, value) in envs {
            command.env(name, value);
        }
        command
            .args(args)
            .output()
            .expect("run loom command with env")
    }

    fn run_ok(&self, args: &[&str]) -> String {
        let output = self.run_output(args);
        assert_success(args, &output);
        String::from_utf8_lossy(&output.stdout).to_string()
    }

    fn json_ok_with_env(&self, args: &[&str], envs: &[(&str, &str)]) -> Value {
        let output = self.run_output_with_env(args, envs);
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
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"embodied grpc physical fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
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
    fs::write(
        kernel_dir.join("treasury.py"),
        "def check_budget(agent_id, cost_usd, org_id=None):\n    return True, 'ok'\n\ndef reserve_runtime_budget(agent_id, estimated_cost, org_id=None, action='', resource='', context=None, policy_ref=''):\n    return {'allowed': True, 'reservation_id': 'bud_embodied', 'reason': 'ok'}\n\ndef commit_runtime_budget(reservation_id, actual_cost_usd, note=''):\n    return {'reservation_id': reservation_id, 'status': 'committed', 'commit_reason': note}\n\ndef release_runtime_budget(reservation_id, reason=''):\n    return {'reservation_id': reservation_id, 'status': 'released', 'release_reason': reason}\n",
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
    let signer = SigningKey::from_bytes(&[31u8; 32]);
    let mut id = [0u8; 32];
    for (index, slot) in id.iter_mut().enumerate() {
        *slot = (index as u8).wrapping_mul(9).wrapping_add(7);
    }
    let scope_cbor = vec![
        0xA1, 0x69, b'e', b'm', b'b', b'o', b'd', b'i', b'e', b'd', 0xF5,
    ];
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

fn write_grpc_physical_shim(script_path: &Path) {
    let script = r#"#!/usr/bin/env bash
set -euo pipefail
capture_path="${LOOM_GRPC_PHYSICAL_SHIM_CAPTURE:-}"
mode="${LOOM_GRPC_PHYSICAL_SHIM_MODE:-ack}"
payload='{}'
target=''
rpc=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d)
      payload="$2"
      shift 2
      ;;
    *)
      if [[ "$1" == -* ]]; then
        if [[ $# -gt 1 && "$2" != -* ]]; then
          shift 2
        else
          shift
        fi
        continue
      fi
      if [[ -z "$target" ]]; then
        target="$1"
      elif [[ -z "$rpc" ]]; then
        rpc="$1"
      fi
      shift
      ;;
  esac
done
if [[ -n "$capture_path" ]]; then
  printf '{"target":"%s","rpc":"%s","payload":%s,"mode":"%s"}\n' "$target" "$rpc" "$payload" "$mode" > "$capture_path"
fi
if [[ "$mode" == "timeout" ]]; then
  printf '{"status":"ok","lifecycle_status":"ack_timeout","ack_received":false,"stream_event_count":2}\n'
else
  printf '{"status":"ok","lifecycle_status":"acknowledged","ack_received":true,"stream_event_count":4}\n'
fi
"#;
    fs::write(script_path, script).expect("write grpc physical shim");
    let mut permissions = fs::metadata(script_path)
        .expect("grpc physical shim metadata")
        .permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(script_path, permissions).expect("chmod grpc physical shim");
}

fn run_grpc_physical_shadow(
    harness: &Harness,
    warrant_path: &Path,
    grpc_shim_path: &Path,
    capture_path: &Path,
    mode: &str,
    extra_args: &[&str],
) -> Value {
    let mut args = vec![
        "shadow",
        "run",
        "--backend",
        "grpc_physical",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_grpc_physical",
        "--resource",
        "external_grpc_physical",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--url",
        "grpc://127.0.0.1:50051",
        "--grpc-service",
        "meridian.embodied.action.v1.PhysicalActionService",
        "--grpc-method",
        "Execute",
        "--grpc-action-kind",
        "physical.move",
        "--grpc-action-objective",
        "move robot to staging point",
        "--physical-robot-id",
        "unitree.go2",
        "--physical-target",
        "warehouse.aisle-7",
        "--physical-command",
        "move_to_pose",
        "--physical-safety-class",
        "restricted",
        "--physical-dry-run",
        "--format",
        "json",
    ];
    args.extend_from_slice(extra_args);
    harness.json_ok_with_env(
        &args,
        &[
            (
                "LOOM_SHADOW_GRPCURL_BIN",
                grpc_shim_path.to_str().expect("shim path"),
            ),
            (
                "LOOM_GRPC_PHYSICAL_SHIM_CAPTURE",
                capture_path.to_str().expect("capture path"),
            ),
            ("LOOM_GRPC_PHYSICAL_SHIM_MODE", mode),
        ],
    )
}

#[test]
fn shadow_run_grpc_physical_backend_writes_embodied_typed_artifacts() {
    let harness = Harness::new("grpc_physical_typed");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);
    let shim_path = harness.home.join("grpcurl-physical-shim.sh");
    write_grpc_physical_shim(&shim_path);
    let capture_path = harness.home.join("grpc-physical-capture.json");

    let capture = run_grpc_physical_shadow(
        &harness,
        &warrant_path,
        &shim_path,
        &capture_path,
        "ack",
        &[
            "--grpc-physical-lifecycle",
            "stream",
            "--grpc-physical-ack-required",
            "--grpc-physical-ack-timeout-seconds",
            "5",
        ],
    );

    assert_eq!(
        capture.get("backend").and_then(Value::as_str),
        Some("grpc_physical")
    );
    assert_eq!(
        capture.get("host_backend").and_then(Value::as_str),
        Some("external_grpc_physical")
    );

    let shim_capture: Value =
        serde_json::from_str(&fs::read_to_string(&capture_path).expect("read shim capture"))
            .expect("parse shim capture");
    assert_eq!(
        shim_capture
            .get("payload")
            .and_then(|value| value.get("schema"))
            .and_then(Value::as_str),
        Some("meridian.embodied.action.v1")
    );
    assert_eq!(
        shim_capture
            .get("payload")
            .and_then(|value| value.get("physical"))
            .and_then(|value| value.get("robot_id"))
            .and_then(Value::as_str),
        Some("unitree.go2")
    );
}

#[test]
fn shadow_run_grpc_physical_stream_ack_lifecycle_records_ack() {
    let harness = Harness::new("grpc_physical_ack");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);
    let shim_path = harness.home.join("grpcurl-physical-shim.sh");
    write_grpc_physical_shim(&shim_path);
    let capture_path = harness.home.join("grpc-physical-capture.json");

    let _ = run_grpc_physical_shadow(
        &harness,
        &warrant_path,
        &shim_path,
        &capture_path,
        "ack",
        &[
            "--grpc-physical-lifecycle",
            "stream",
            "--grpc-physical-ack-required",
            "--grpc-physical-ack-timeout-seconds",
            "5",
            "--grpc-physical-cancel-on-ack-timeout",
            "--grpc-physical-remediation-profile",
            "strict",
        ],
    );

    let diagnostics_path = harness
        .root
        .join("artifacts/shadow/grpc_action/latest.json");
    let diagnostics: Value = serde_json::from_str(
        &fs::read_to_string(&diagnostics_path).expect("read grpc physical diagnostics"),
    )
    .expect("parse grpc physical diagnostics");
    assert_eq!(
        diagnostics
            .get("grpc_lifecycle_ack_received")
            .and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        diagnostics
            .get("grpc_lifecycle_cancelled")
            .and_then(Value::as_bool),
        Some(false)
    );
    let shadow_report = harness.run_ok(&["shadow", "report", "--root", harness.root_str()]);
    assert!(
        shadow_report.contains("grpc_lifecycle_mode:"),
        "shadow report should render lifecycle metrics\n{}",
        shadow_report
    );
    assert!(
        shadow_report.contains("grpc_remediation_profile:"),
        "shadow report should render remediation policy\n{}",
        shadow_report
    );
}

#[test]
fn shadow_run_grpc_physical_stream_ack_timeout_cancels() {
    let harness = Harness::new("grpc_physical_timeout");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);
    let shim_path = harness.home.join("grpcurl-physical-shim.sh");
    write_grpc_physical_shim(&shim_path);
    let capture_path = harness.home.join("grpc-physical-capture.json");

    let _ = run_grpc_physical_shadow(
        &harness,
        &warrant_path,
        &shim_path,
        &capture_path,
        "timeout",
        &[
            "--grpc-physical-lifecycle",
            "stream",
            "--grpc-physical-ack-required",
            "--grpc-physical-ack-timeout-seconds",
            "2",
            "--grpc-physical-cancel-on-ack-timeout",
            "--grpc-physical-remediation-profile",
            "strict",
        ],
    );

    let diagnostics_path = harness
        .root
        .join("artifacts/shadow/grpc_action/latest.json");
    let diagnostics: Value = serde_json::from_str(
        &fs::read_to_string(&diagnostics_path).expect("read grpc physical diagnostics"),
    )
    .expect("parse grpc physical diagnostics");
    assert_eq!(
        diagnostics
            .get("grpc_lifecycle_ack_received")
            .and_then(Value::as_bool),
        Some(false)
    );
    assert_eq!(
        diagnostics
            .get("grpc_lifecycle_cancelled")
            .and_then(Value::as_bool),
        Some(true)
    );
    assert_eq!(
        diagnostics
            .get("grpc_lifecycle_cancel_reason")
            .and_then(Value::as_str),
        Some("ack_timeout")
    );
}

#[test]
fn shadow_run_grpc_physical_requires_physical_fields() {
    let harness = Harness::new("grpc_physical_missing_required");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);
    let output = harness.run_output(&[
        "shadow",
        "run",
        "--backend",
        "grpc_physical",
        "--root",
        harness.root_str(),
        "--kernel-path",
        harness.kernel_str(),
        "--agent-id",
        "agent_atlas",
        "--org-id",
        "org_demo",
        "--action-type",
        "shadow_grpc_physical",
        "--resource",
        "external_grpc_physical",
        "--warrant-file",
        warrant_path.to_str().expect("warrant path"),
        "--url",
        "grpc://127.0.0.1:50051",
        "--grpc-service",
        "meridian.embodied.action.v1.PhysicalActionService",
        "--grpc-method",
        "Execute",
        "--grpc-action-kind",
        "physical.move",
        "--grpc-action-objective",
        "move robot to staging point",
        "--physical-robot-id",
        "unitree.go2",
        "--physical-command",
        "move_to_pose",
        "--physical-safety-class",
        "restricted",
        "--format",
        "json",
    ]);
    assert!(!output.status.success(), "command should fail");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("--physical-target"),
        "stderr should mention missing --physical-target: {}",
        stderr
    );
}

#[test]
fn shadow_run_grpc_physical_gracefully_degrades_when_grpcurl_missing() {
    let harness = Harness::new("grpc_physical_missing_grpcurl");
    let warrant_path = harness.home.join("shadow-warrant.json");
    write_signed_warrant(&warrant_path);

    let capture = harness.json_ok_with_env(
        &[
            "shadow",
            "run",
            "--backend",
            "grpc_physical",
            "--root",
            harness.root_str(),
            "--kernel-path",
            harness.kernel_str(),
            "--agent-id",
            "agent_atlas",
            "--org-id",
            "org_demo",
            "--action-type",
            "shadow_grpc_physical",
            "--resource",
            "external_grpc_physical",
            "--warrant-file",
            warrant_path.to_str().expect("warrant path"),
            "--url",
            "grpc://127.0.0.1:50051",
            "--grpc-service",
            "meridian.embodied.action.v1.PhysicalActionService",
            "--grpc-method",
            "Execute",
            "--grpc-action-kind",
            "physical.move",
            "--grpc-action-objective",
            "move robot to staging point",
            "--physical-robot-id",
            "unitree.go2",
            "--physical-target",
            "warehouse.aisle-7",
            "--physical-command",
            "move_to_pose",
            "--physical-safety-class",
            "restricted",
            "--grpc-physical-lifecycle",
            "stream",
            "--grpc-physical-ack-required",
            "--grpc-physical-ack-timeout-seconds",
            "5",
            "--format",
            "json",
        ],
        &[("LOOM_SHADOW_GRPCURL_BIN", "/tmp/does-not-exist-grpcurl")],
    );
    assert_eq!(
        capture.get("status").and_then(Value::as_str),
        Some("shadow_run_captured")
    );
    assert_eq!(
        capture
            .get("warrant_binding_status")
            .and_then(Value::as_str),
        Some("verified")
    );
    let response = capture
        .get("host_response_json")
        .and_then(Value::as_str)
        .unwrap_or("");
    assert!(
        response.contains("grpc_physical_transport_unavailable"),
        "host response should report graceful transport fallback: {}",
        response
    );
}
