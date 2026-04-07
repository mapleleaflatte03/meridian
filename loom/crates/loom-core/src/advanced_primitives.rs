use crate::LoomResult;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FileAccessMode {
    ReadOnly,
    AppendOnly,
    ReplaceExisting,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileAccessScope {
    pub root: String,
    pub max_bytes: usize,
    pub allow_hidden: bool,
    pub follow_symlinks: bool,
}

impl Default for FileAccessScope {
    fn default() -> Self {
        Self {
            root: ".".to_string(),
            max_bytes: 65_536,
            allow_hidden: false,
            follow_symlinks: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BoundedFileReadRequest {
    pub scope: FileAccessScope,
    pub path: String,
    pub offset_bytes: usize,
    pub max_bytes: usize,
}

impl Default for BoundedFileReadRequest {
    fn default() -> Self {
        Self {
            scope: FileAccessScope::default(),
            path: String::new(),
            offset_bytes: 0,
            max_bytes: 8_192,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BoundedFileReadResult {
    pub canonical_path: String,
    pub content_utf8: String,
    pub bytes_read: usize,
    pub truncated: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BoundedFileWriteRequest {
    pub scope: FileAccessScope,
    pub path: String,
    pub mode: FileAccessMode,
    pub content_utf8: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BoundedFileWriteResult {
    pub canonical_path: String,
    pub bytes_written: usize,
    pub replaced_existing: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TerminalIsolationTier {
    WorkspaceScoped,
    RepositoryScoped,
    TempdirScoped,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TerminalStreamCapture {
    None,
    StdoutOnly,
    StderrOnly,
    StdoutAndStderr,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TerminalExecRequest {
    pub argv: Vec<String>,
    pub working_dir: String,
    pub stdin_utf8: String,
    pub env_allowlist: Vec<String>,
    pub timeout_ms: u64,
    pub max_output_bytes: usize,
    pub isolation_tier: TerminalIsolationTier,
    pub stream_capture: TerminalStreamCapture,
    pub reject_shell_metacharacters: bool,
}

impl Default for TerminalExecRequest {
    fn default() -> Self {
        Self {
            argv: Vec::new(),
            working_dir: ".".to_string(),
            stdin_utf8: String::new(),
            env_allowlist: Vec::new(),
            timeout_ms: 2_000,
            max_output_bytes: 16_384,
            isolation_tier: TerminalIsolationTier::WorkspaceScoped,
            stream_capture: TerminalStreamCapture::StdoutAndStderr,
            reject_shell_metacharacters: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TerminalExecResult {
    pub exit_code: Option<i32>,
    pub stdout_utf8: String,
    pub stderr_utf8: String,
    pub timed_out: bool,
    pub truncated: bool,
}

pub trait SystemAdapter {
    fn read_file(&self, request: &BoundedFileReadRequest) -> LoomResult<BoundedFileReadResult>;
    fn write_file(&self, request: &BoundedFileWriteRequest) -> LoomResult<BoundedFileWriteResult>;
    fn exec_terminal(&self, request: &TerminalExecRequest) -> LoomResult<TerminalExecResult>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BrowserWaitCondition {
    None,
    DomContentLoaded,
    NetworkIdle,
    Selector(String),
    Text(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BrowserDomActionKind {
    Click,
    Hover,
    ExtractText,
    Type(String),
    Select(String),
    Press(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BrowserNavigateRequest {
    pub session_id: String,
    pub url: String,
    pub allowed_hosts: Vec<String>,
    pub wait_for: BrowserWaitCondition,
    pub timeout_ms: u64,
    pub capture_semantic_snapshot: bool,
    pub max_snapshot_bytes: usize,
}

impl Default for BrowserNavigateRequest {
    fn default() -> Self {
        Self {
            session_id: String::new(),
            url: String::new(),
            allowed_hosts: Vec::new(),
            wait_for: BrowserWaitCondition::DomContentLoaded,
            timeout_ms: 4_000,
            capture_semantic_snapshot: true,
            max_snapshot_bytes: 24_576,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BrowserNavigateResult {
    pub session_id: String,
    pub final_url: String,
    pub title: String,
    pub http_status: Option<u16>,
    pub semantic_snapshot_id: Option<String>,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BrowserDomActionRequest {
    pub session_id: String,
    pub selector: String,
    pub action: BrowserDomActionKind,
    pub timeout_ms: u64,
    pub expected_text: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BrowserDomActionResult {
    pub session_id: String,
    pub matched_nodes: usize,
    pub extracted_text: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SemanticSnapshotFormat {
    AccessibilityTree,
    Markdown,
    Json,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SemanticSnapshotRequest {
    pub session_id: String,
    pub format: SemanticSnapshotFormat,
    pub include_links: bool,
    pub max_nodes: usize,
    pub max_bytes: usize,
}

impl Default for SemanticSnapshotRequest {
    fn default() -> Self {
        Self {
            session_id: String::new(),
            format: SemanticSnapshotFormat::AccessibilityTree,
            include_links: true,
            max_nodes: 256,
            max_bytes: 24_576,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SemanticSnapshot {
    pub session_id: String,
    pub format: SemanticSnapshotFormat,
    pub body: String,
    pub truncated: bool,
    pub captured_at_unix_ms: u64,
}

pub trait BrowserAdapter {
    fn navigate(&self, request: &BrowserNavigateRequest) -> LoomResult<BrowserNavigateResult>;
    fn interact(&self, request: &BrowserDomActionRequest) -> LoomResult<BrowserDomActionResult>;
    fn semantic_snapshot(&self, request: &SemanticSnapshotRequest) -> LoomResult<SemanticSnapshot>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MemoryRecordKind {
    Observation,
    Decision,
    Preference,
    Plan,
    ExternalFact,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryRecord {
    pub memory_id: String,
    pub agent_id: String,
    pub namespace: String,
    pub kind: MemoryRecordKind,
    pub summary: String,
    pub detail: String,
    pub tags: Vec<String>,
    pub source: String,
    pub written_at_unix_ms: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryQuery {
    pub agent_id: String,
    pub namespace: String,
    pub text_query: String,
    pub tags_any: Vec<String>,
    pub limit: usize,
    pub cursor: String,
}

impl Default for MemoryQuery {
    fn default() -> Self {
        Self {
            agent_id: String::new(),
            namespace: String::new(),
            text_query: String::new(),
            tags_any: Vec::new(),
            limit: 10,
            cursor: String::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryMatch {
    pub record: MemoryRecord,
    pub score_ppm: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemorySearchResult {
    pub matches: Vec<MemoryMatch>,
    pub next_cursor: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryStateWrite {
    pub agent_id: String,
    pub scope: String,
    pub key: String,
    pub value_json: String,
    pub expected_revision: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MemoryStateEntry {
    pub agent_id: String,
    pub scope: String,
    pub key: String,
    pub value_json: String,
    pub revision: u64,
    pub updated_at_unix_ms: u64,
}

pub trait MemoryStore {
    fn append_memory(&self, record: &MemoryRecord) -> LoomResult<String>;
    fn search_memory(&self, query: &MemoryQuery) -> LoomResult<MemorySearchResult>;
    fn load_state(
        &self,
        agent_id: &str,
        scope: &str,
        key: &str,
    ) -> LoomResult<Option<MemoryStateEntry>>;
    fn save_state(&self, write: &MemoryStateWrite) -> LoomResult<MemoryStateEntry>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HeartbeatSchedule {
    Once {
        not_before_unix_ms: u64,
    },
    Interval {
        every_seconds: u64,
        jitter_seconds: u64,
    },
    Cron {
        expression: String,
        timezone: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HeartbeatStatus {
    Scheduled,
    Paused,
    Claimed,
    Running,
    Failed,
    Completed,
    Cancelled,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatRegistration {
    pub heartbeat_id: String,
    pub agent_id: String,
    pub capability_name: String,
    pub schedule: HeartbeatSchedule,
    pub payload_json: String,
    pub max_attempts: u32,
    pub max_parallelism: u32,
    pub enabled: bool,
}

impl Default for HeartbeatRegistration {
    fn default() -> Self {
        Self {
            heartbeat_id: String::new(),
            agent_id: String::new(),
            capability_name: String::new(),
            schedule: HeartbeatSchedule::Interval {
                every_seconds: 300,
                jitter_seconds: 15,
            },
            payload_json: String::new(),
            max_attempts: 3,
            max_parallelism: 1,
            enabled: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatReceipt {
    pub heartbeat_id: String,
    pub status: HeartbeatStatus,
    pub next_fire_at_unix_ms: Option<u64>,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatLeaseRequest {
    pub now_unix_ms: u64,
    pub limit: usize,
    pub worker_id: String,
}

impl Default for HeartbeatLeaseRequest {
    fn default() -> Self {
        Self {
            now_unix_ms: 0,
            limit: 1,
            worker_id: String::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HeartbeatDispatch {
    pub heartbeat_id: String,
    pub lease_id: String,
    pub agent_id: String,
    pub capability_name: String,
    pub payload_json: String,
    pub fire_at_unix_ms: u64,
    pub attempt: u32,
}

pub trait HeartbeatScheduler {
    fn register(&self, registration: &HeartbeatRegistration) -> LoomResult<HeartbeatReceipt>;
    fn pause(&self, heartbeat_id: &str) -> LoomResult<HeartbeatReceipt>;
    fn cancel(&self, heartbeat_id: &str) -> LoomResult<HeartbeatReceipt>;
    fn lease_due(&self, request: &HeartbeatLeaseRequest) -> LoomResult<Vec<HeartbeatDispatch>>;
    fn acknowledge(
        &self,
        heartbeat_id: &str,
        lease_id: &str,
        status: HeartbeatStatus,
    ) -> LoomResult<HeartbeatReceipt>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OmniChannelKind {
    WhatsApp,
    Telegram,
    Discord,
    Slack,
    WebSocketDirect,
    Custom(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OmniMessageDirection {
    Inbound,
    Outbound,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OmniChannelAddress {
    pub channel: OmniChannelKind,
    pub workspace_id: String,
    pub thread_id: String,
    pub participant_id: String,
    pub display_name: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OmniAttachmentRef {
    pub content_type: String,
    pub url: String,
    pub name: String,
    pub size_bytes: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OmniMessageEnvelope {
    pub message_id: String,
    pub direction: OmniMessageDirection,
    pub address: OmniChannelAddress,
    pub text: String,
    pub attachments: Vec<OmniAttachmentRef>,
    pub correlation_id: String,
    pub observed_at_unix_ms: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OmniWebSocketBinding {
    pub gateway_id: String,
    pub websocket_url: String,
    pub auth_scheme: String,
    pub subscribed_channels: Vec<OmniChannelKind>,
    pub heartbeat_seconds: u64,
}

impl Default for OmniWebSocketBinding {
    fn default() -> Self {
        Self {
            gateway_id: String::new(),
            websocket_url: String::new(),
            auth_scheme: "bearer".to_string(),
            subscribed_channels: vec![OmniChannelKind::WebSocketDirect],
            heartbeat_seconds: 30,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OmniDeliveryReceipt {
    pub gateway_id: String,
    pub message_id: String,
    pub accepted: bool,
    pub remote_message_id: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OmniReceiveCursor {
    pub gateway_id: String,
    pub cursor: String,
    pub limit: usize,
}

impl Default for OmniReceiveCursor {
    fn default() -> Self {
        Self {
            gateway_id: String::new(),
            cursor: String::new(),
            limit: 25,
        }
    }
}

pub trait OmniChannelGateway {
    fn register_websocket(&self, binding: &OmniWebSocketBinding) -> LoomResult<String>;
    fn send(&self, message: &OmniMessageEnvelope) -> LoomResult<OmniDeliveryReceipt>;
    fn receive(&self, cursor: &OmniReceiveCursor) -> LoomResult<Vec<OmniMessageEnvelope>>;
    fn acknowledge(&self, gateway_id: &str, message_id: &str) -> LoomResult<OmniDeliveryReceipt>;
}

#[cfg(test)]
mod tests {
    use super::*;

    struct DummySystem;
    struct DummyBrowser;
    struct DummyMemory;
    struct DummyHeartbeat;
    struct DummyGateway;

    impl SystemAdapter for DummySystem {
        fn read_file(&self, request: &BoundedFileReadRequest) -> LoomResult<BoundedFileReadResult> {
            Ok(BoundedFileReadResult {
                canonical_path: request.path.clone(),
                content_utf8: String::new(),
                bytes_read: 0,
                truncated: false,
            })
        }

        fn write_file(
            &self,
            request: &BoundedFileWriteRequest,
        ) -> LoomResult<BoundedFileWriteResult> {
            Ok(BoundedFileWriteResult {
                canonical_path: request.path.clone(),
                bytes_written: request.content_utf8.len(),
                replaced_existing: matches!(request.mode, FileAccessMode::ReplaceExisting),
            })
        }

        fn exec_terminal(&self, _request: &TerminalExecRequest) -> LoomResult<TerminalExecResult> {
            Ok(TerminalExecResult {
                exit_code: Some(0),
                stdout_utf8: String::new(),
                stderr_utf8: String::new(),
                timed_out: false,
                truncated: false,
            })
        }
    }

    impl BrowserAdapter for DummyBrowser {
        fn navigate(&self, request: &BrowserNavigateRequest) -> LoomResult<BrowserNavigateResult> {
            Ok(BrowserNavigateResult {
                session_id: request.session_id.clone(),
                final_url: request.url.clone(),
                title: String::new(),
                http_status: Some(200),
                semantic_snapshot_id: None,
                note: String::new(),
            })
        }

        fn interact(
            &self,
            request: &BrowserDomActionRequest,
        ) -> LoomResult<BrowserDomActionResult> {
            Ok(BrowserDomActionResult {
                session_id: request.session_id.clone(),
                matched_nodes: 1,
                extracted_text: String::new(),
                note: String::new(),
            })
        }

        fn semantic_snapshot(
            &self,
            request: &SemanticSnapshotRequest,
        ) -> LoomResult<SemanticSnapshot> {
            Ok(SemanticSnapshot {
                session_id: request.session_id.clone(),
                format: request.format.clone(),
                body: String::new(),
                truncated: false,
                captured_at_unix_ms: 0,
            })
        }
    }

    impl MemoryStore for DummyMemory {
        fn append_memory(&self, record: &MemoryRecord) -> LoomResult<String> {
            Ok(record.memory_id.clone())
        }

        fn search_memory(&self, _query: &MemoryQuery) -> LoomResult<MemorySearchResult> {
            Ok(MemorySearchResult {
                matches: Vec::new(),
                next_cursor: String::new(),
                note: String::new(),
            })
        }

        fn load_state(
            &self,
            _agent_id: &str,
            _scope: &str,
            _key: &str,
        ) -> LoomResult<Option<MemoryStateEntry>> {
            Ok(None)
        }

        fn save_state(&self, write: &MemoryStateWrite) -> LoomResult<MemoryStateEntry> {
            Ok(MemoryStateEntry {
                agent_id: write.agent_id.clone(),
                scope: write.scope.clone(),
                key: write.key.clone(),
                value_json: write.value_json.clone(),
                revision: 1,
                updated_at_unix_ms: 0,
            })
        }
    }

    impl HeartbeatScheduler for DummyHeartbeat {
        fn register(&self, registration: &HeartbeatRegistration) -> LoomResult<HeartbeatReceipt> {
            Ok(HeartbeatReceipt {
                heartbeat_id: registration.heartbeat_id.clone(),
                status: HeartbeatStatus::Scheduled,
                next_fire_at_unix_ms: Some(1),
                note: String::new(),
            })
        }

        fn pause(&self, heartbeat_id: &str) -> LoomResult<HeartbeatReceipt> {
            Ok(HeartbeatReceipt {
                heartbeat_id: heartbeat_id.to_string(),
                status: HeartbeatStatus::Paused,
                next_fire_at_unix_ms: None,
                note: String::new(),
            })
        }

        fn cancel(&self, heartbeat_id: &str) -> LoomResult<HeartbeatReceipt> {
            Ok(HeartbeatReceipt {
                heartbeat_id: heartbeat_id.to_string(),
                status: HeartbeatStatus::Cancelled,
                next_fire_at_unix_ms: None,
                note: String::new(),
            })
        }

        fn lease_due(
            &self,
            _request: &HeartbeatLeaseRequest,
        ) -> LoomResult<Vec<HeartbeatDispatch>> {
            Ok(Vec::new())
        }

        fn acknowledge(
            &self,
            heartbeat_id: &str,
            _lease_id: &str,
            status: HeartbeatStatus,
        ) -> LoomResult<HeartbeatReceipt> {
            Ok(HeartbeatReceipt {
                heartbeat_id: heartbeat_id.to_string(),
                status,
                next_fire_at_unix_ms: None,
                note: String::new(),
            })
        }
    }

    impl OmniChannelGateway for DummyGateway {
        fn register_websocket(&self, binding: &OmniWebSocketBinding) -> LoomResult<String> {
            Ok(binding.gateway_id.clone())
        }

        fn send(&self, message: &OmniMessageEnvelope) -> LoomResult<OmniDeliveryReceipt> {
            Ok(OmniDeliveryReceipt {
                gateway_id: message.address.workspace_id.clone(),
                message_id: message.message_id.clone(),
                accepted: true,
                remote_message_id: message.message_id.clone(),
                note: String::new(),
            })
        }

        fn receive(&self, _cursor: &OmniReceiveCursor) -> LoomResult<Vec<OmniMessageEnvelope>> {
            Ok(Vec::new())
        }

        fn acknowledge(
            &self,
            gateway_id: &str,
            message_id: &str,
        ) -> LoomResult<OmniDeliveryReceipt> {
            Ok(OmniDeliveryReceipt {
                gateway_id: gateway_id.to_string(),
                message_id: message_id.to_string(),
                accepted: true,
                remote_message_id: message_id.to_string(),
                note: String::new(),
            })
        }
    }

    #[test]
    fn defaults_stay_bounded() {
        assert_eq!(FileAccessScope::default().max_bytes, 65_536);
        assert_eq!(TerminalExecRequest::default().timeout_ms, 2_000);
        assert!(BrowserNavigateRequest::default().capture_semantic_snapshot);
        assert_eq!(MemoryQuery::default().limit, 10);
        assert_eq!(OmniWebSocketBinding::default().heartbeat_seconds, 30);
        match HeartbeatRegistration::default().schedule {
            HeartbeatSchedule::Interval {
                every_seconds,
                jitter_seconds,
            } => {
                assert_eq!(every_seconds, 300);
                assert_eq!(jitter_seconds, 15);
            }
            _ => panic!("unexpected heartbeat default"),
        }
    }

    #[test]
    fn trait_surfaces_are_object_safe_and_callable() {
        let system: &dyn SystemAdapter = &DummySystem;
        let browser: &dyn BrowserAdapter = &DummyBrowser;
        let memory: &dyn MemoryStore = &DummyMemory;
        let heartbeat: &dyn HeartbeatScheduler = &DummyHeartbeat;
        let gateway: &dyn OmniChannelGateway = &DummyGateway;

        let read = system
            .read_file(&BoundedFileReadRequest {
                path: "README.md".to_string(),
                ..BoundedFileReadRequest::default()
            })
            .expect("read file");
        assert_eq!(read.canonical_path, "README.md");

        let navigation = browser
            .navigate(&BrowserNavigateRequest {
                session_id: "browser_1".to_string(),
                url: "https://example.com".to_string(),
                ..BrowserNavigateRequest::default()
            })
            .expect("navigate");
        assert_eq!(navigation.session_id, "browser_1");

        let memory_id = memory
            .append_memory(&MemoryRecord {
                memory_id: "mem_1".to_string(),
                agent_id: "agent_atlas".to_string(),
                namespace: "research".to_string(),
                kind: MemoryRecordKind::Observation,
                summary: "summary".to_string(),
                detail: String::new(),
                tags: vec!["web".to_string()],
                source: "test".to_string(),
                written_at_unix_ms: 0,
            })
            .expect("append memory");
        assert_eq!(memory_id, "mem_1");

        let receipt = heartbeat
            .register(&HeartbeatRegistration {
                heartbeat_id: "beat_1".to_string(),
                agent_id: "agent_atlas".to_string(),
                capability_name: "intelligence_on_demand_research".to_string(),
                ..HeartbeatRegistration::default()
            })
            .expect("register heartbeat");
        assert_eq!(receipt.status, HeartbeatStatus::Scheduled);

        let gateway_id = gateway
            .register_websocket(&OmniWebSocketBinding {
                gateway_id: "gateway_1".to_string(),
                websocket_url: "wss://gateway.example/ws".to_string(),
                ..OmniWebSocketBinding::default()
            })
            .expect("register websocket");
        assert_eq!(gateway_id, "gateway_1");
    }
}
