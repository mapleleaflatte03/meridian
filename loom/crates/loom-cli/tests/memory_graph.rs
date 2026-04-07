use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_COUNTER: AtomicU64 = AtomicU64::new(0);

fn unique_temp_dir(label: &str) -> PathBuf {
    let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "loom_memory_graph_{}_{}_{}",
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
    fn new(label: &str, restrict_replay: bool) -> Self {
        let home = unique_temp_dir(label);
        let root = home.join(".local/share/meridian-loom/runtime/default");
        let kernel = home.join("kernel");
        scaffold_kernel_fixture(&kernel, restrict_replay);
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

fn scaffold_kernel_fixture(root: &Path, restrict_replay: bool) {
    let kernel_dir = root.join("kernel");
    fs::create_dir_all(&kernel_dir).expect("kernel dir");
    fs::write(
        kernel_dir.join("runtimes.json"),
        "{\n  \"runtimes\": {\n    \"local_kernel\": {\"id\": \"local_kernel\", \"label\": \"Local Kernel Runtime\"},\n    \"loom_native\": {\"status\": \"official\", \"notes\": \"memory graph fixture\", \"contract_compliance\": {\"agent_identity\": true, \"action_envelope\": true, \"cost_attribution\": true, \"approval_hook\": true, \"audit_emission\": true, \"sanction_controls\": true, \"budget_gate\": true}}\n  }\n}\n",
    )
    .expect("write runtimes");
    fs::write(
        kernel_dir.join("agent_registry.py"),
        "import json, sys\nagent_id = sys.argv[sys.argv.index('--agent_id') + 1]\norg_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'\nprint(json.dumps({'id': agent_id, 'name': 'MemoryAgent', 'org_id': org_id, 'role': 'analyst', 'economy_key': 'atlas', 'approval_required': False, 'budget': {'max_per_run_usd': 1.0}, 'runtime_binding': {'runtime_id': 'local_kernel', 'runtime_label': 'Local Kernel Runtime', 'bound_org_id': org_id, 'boundary_name': 'workspace', 'identity_model': 'session', 'runtime_registered': True, 'registration_status': 'registered'}}, indent=2))\n",
    )
    .expect("write registry");
    let restrictions = if restrict_replay {
        "['memory_replay']"
    } else {
        "[]"
    };
    fs::write(
        kernel_dir.join("court.py"),
        format!(
            "def get_restrictions(agent_id, org_id=None):\n    return {}\n",
            restrictions
        ),
    )
    .expect("write court");
    fs::write(
        kernel_dir.join("authority.py"),
        "def check_authority(agent_id, action, org_id=None):\n    return True, 'ok'\n",
    )
    .expect("write authority");
}

fn write_memory_series(harness: &Harness, agent_id: &str) {
    harness.run_ok(&[
        "memory",
        "write",
        "--root",
        harness.root_str(),
        "--agent-id",
        agent_id,
        "--category",
        "research",
        "--key",
        "strategy",
        "--content",
        "v1",
        "--source",
        "test",
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "memory",
        "write",
        "--root",
        harness.root_str(),
        "--agent-id",
        agent_id,
        "--category",
        "research",
        "--key",
        "strategy",
        "--content",
        "v2",
        "--source",
        "test",
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "memory",
        "write",
        "--root",
        harness.root_str(),
        "--agent-id",
        agent_id,
        "--category",
        "research",
        "--key",
        "strategy",
        "--content",
        "v3",
        "--source",
        "test",
        "--format",
        "json",
    ]);
    harness.run_ok(&[
        "memory",
        "write",
        "--root",
        harness.root_str(),
        "--agent-id",
        agent_id,
        "--category",
        "research",
        "--key",
        "risk",
        "--content",
        "low",
        "--source",
        "test",
        "--format",
        "json",
    ]);
}

fn source_write_node_ids(harness: &Harness, agent_id: &str) -> Vec<String> {
    let receipts = harness.json_ok(&[
        "memory",
        "receipts",
        "--root",
        harness.root_str(),
        "--agent-id",
        agent_id,
        "--limit",
        "50",
        "--format",
        "json",
    ]);
    receipts
        .as_array()
        .expect("receipts array")
        .iter()
        .filter(|item| item.get("operation").and_then(Value::as_str) == Some("write"))
        .filter_map(|item| item.get("receipt_hash").and_then(Value::as_str))
        .map(|value| value.to_string())
        .collect()
}

#[test]
fn memory_graph_inspect_renders_compact_lineage_tree() {
    let harness = Harness::new("graph_inspect", false);
    write_memory_series(&harness, "agent_source");
    let nodes = source_write_node_ids(&harness, "agent_source");
    assert!(nodes.len() >= 3, "expected at least 3 write nodes");

    let mut selected_graph: Option<(String, Value)> = None;
    for node in &nodes {
        let candidate = harness.json_ok(&[
            "memory",
            "graph",
            "inspect",
            "agent_source",
            "--node-id",
            node,
            "--direction",
            "both",
            "--limit",
            "10",
            "--root",
            harness.root_str(),
            "--format",
            "json",
        ]);
        let has_ancestors = candidate
            .get("ancestor_nodes")
            .and_then(Value::as_array)
            .map(|items| !items.is_empty())
            .unwrap_or(false);
        let has_descendants = candidate
            .get("descendant_nodes")
            .and_then(Value::as_array)
            .map(|items| !items.is_empty())
            .unwrap_or(false);
        if has_ancestors && has_descendants {
            selected_graph = Some((node.clone(), candidate));
            break;
        }
    }
    let (focus, graph) =
        selected_graph.expect("expected lineage focus with both ancestors and descendants");
    assert_eq!(
        graph.get("status").and_then(Value::as_str),
        Some("memory_graph_inspect")
    );
    assert_eq!(
        graph
            .get("focus_node")
            .and_then(|value| value.get("node_id"))
            .and_then(Value::as_str),
        Some(focus.as_str())
    );
    assert!(graph
        .get("ancestor_nodes")
        .and_then(Value::as_array)
        .map(|items| !items.is_empty())
        .unwrap_or(false));
    assert!(graph
        .get("descendant_nodes")
        .and_then(Value::as_array)
        .map(|items| !items.is_empty())
        .unwrap_or(false));
}

#[test]
fn memory_replay_subgraph_is_blocked_by_court_gate() {
    let harness = Harness::new("replay_blocked", true);
    write_memory_series(&harness, "agent_source");
    let nodes = source_write_node_ids(&harness, "agent_source");
    assert!(!nodes.is_empty(), "expected write nodes");
    let focus = nodes[0].clone();

    let replay = harness.json_ok(&[
        "memory",
        "replay",
        "agent_source",
        "--target-agent-id",
        "agent_target",
        "--node-id",
        &focus,
        "--direction",
        "both",
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
        replay.get("status").and_then(Value::as_str),
        Some("memory_replay_blocked")
    );
    assert_eq!(
        replay.get("court_status").and_then(Value::as_str),
        Some("blocked")
    );
    assert_eq!(
        replay.get("replayed_entries").and_then(Value::as_u64),
        Some(0)
    );
}

#[test]
fn memory_replay_subgraph_replays_selected_nodes_when_allowed() {
    let harness = Harness::new("replay_allowed", false);
    write_memory_series(&harness, "agent_source");
    let nodes = source_write_node_ids(&harness, "agent_source");
    assert!(nodes.len() >= 2, "expected write nodes");
    let focus = nodes[1].clone();

    let replay = harness.json_ok(&[
        "memory",
        "replay",
        "agent_source",
        "--target-agent-id",
        "agent_target",
        "--node-id",
        &focus,
        "--direction",
        "ancestors",
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
        replay.get("status").and_then(Value::as_str),
        Some("memory_replay_applied")
    );
    assert_eq!(
        replay.get("court_status").and_then(Value::as_str),
        Some("clear")
    );
    assert_eq!(
        replay.get("authority_status").and_then(Value::as_str),
        Some("allowed")
    );
    assert!(replay
        .get("selected_node_ids")
        .and_then(Value::as_array)
        .map(|items| !items.is_empty())
        .unwrap_or(false));
    assert!(
        replay
            .get("replayed_entries")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            >= 1
    );

    let target_entries = harness.json_ok(&[
        "memory",
        "search",
        "--root",
        harness.root_str(),
        "--agent-id",
        "agent_target",
        "--category",
        "research",
        "--format",
        "json",
    ]);
    let entries = target_entries.as_array().expect("target entries");
    assert!(
        !entries.is_empty(),
        "target memory should receive replayed entries"
    );
}

#[test]
fn memory_fork_creates_native_artifact_and_target_entries() {
    let harness = Harness::new("fork_native", false);
    write_memory_series(&harness, "agent_source");

    let fork = harness.json_ok(&[
        "memory",
        "fork",
        "agent_source",
        "--target-agent-id",
        "agent_target",
        "--branch",
        "full-system",
        "--root",
        harness.root_str(),
        "--format",
        "json",
    ]);
    assert_eq!(
        fork.get("status").and_then(Value::as_str),
        Some("memory_fork_created")
    );
    assert!(
        fork.get("forked_entries")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            >= 1
    );
    let artifact_path = PathBuf::from(
        fork.get("artifact_path")
            .and_then(Value::as_str)
            .unwrap_or_default(),
    );
    assert!(
        artifact_path.exists(),
        "memory fork artifact should exist: {}",
        artifact_path.display()
    );

    let target_entries = harness.json_ok(&[
        "memory",
        "search",
        "--root",
        harness.root_str(),
        "--agent-id",
        "agent_target",
        "--category",
        "research",
        "--format",
        "json",
    ]);
    let entries = target_entries.as_array().expect("target entries");
    assert!(
        !entries.is_empty(),
        "target memory should receive forked entries"
    );
}
