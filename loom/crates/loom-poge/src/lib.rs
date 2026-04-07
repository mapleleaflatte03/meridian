//! `loom-poge` — Proof of Governed Execution (PoGE) cryptography library.
//!
//! Implements RFC-MERIDIAN-0001: SHA-256-based host-call receipt hashing,
//! binary Merkle tree construction, and audit-root finalization for
//! EVM-compatible on-chain settlement.

use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use sha2::{Digest, Sha256};

pub mod sp1;
pub use sp1::{ParseZkProofBackendError, ZkPoGEProof, ZkProofBackend};

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Errors produced by the PoGE system.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PoGEError {
    /// Trace has reached [`MAX_TRACE_RECEIPTS`] and cannot accept more events.
    TraceOverflow,
    /// Session was finalized with no recorded host-calls.
    EmptyTrace,
    /// The [`KernelWarrant`]'s expiry has passed at the time of a host-call.
    WarrantExpired,
    /// Ed25519 signature on the [`KernelWarrant`] is invalid.
    WarrantSignatureInvalid,
    /// EVM settlement transaction failed.
    SettlementFailed(String),
}

impl std::fmt::Display for PoGEError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TraceOverflow => write!(f, "PoGE trace overflow: max receipts reached"),
            Self::EmptyTrace => write!(f, "PoGE trace is empty; cannot finalize"),
            Self::WarrantExpired => write!(f, "KernelWarrant has expired"),
            Self::WarrantSignatureInvalid => write!(f, "KernelWarrant signature is invalid"),
            Self::SettlementFailed(msg) => write!(f, "EVM settlement failed: {}", msg),
        }
    }
}

impl std::error::Error for PoGEError {}

// ---------------------------------------------------------------------------
// KernelWarrant
// ---------------------------------------------------------------------------

/// A governance credential issued by the Meridian Kernel before execution
/// begins. The `id` field is the canonical 32-byte warrant identifier that
/// flows into every [`HostCallReceipt`] produced during the session it governs.
///
/// # Security Note
/// `KernelWarrant` is issued out-of-band by the Kernel and passed into the
/// Loom host at session start. It MUST be verified (signature check over
/// `id || scope_hash || expiry_epoch_ms`) before being accepted by the
/// [`PoGEInterceptor`]. The signature verification algorithm is Ed25519 using
/// the Kernel's published long-term key.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KernelWarrant {
    /// Globally unique 32-byte identifier. Used as a binding tag in every
    /// [`HostCallReceipt`] produced under this warrant.
    pub id: [u8; 32],

    /// CBOR-encoded scope descriptor.
    pub scope_cbor: Vec<u8>,

    /// UTC milliseconds at which this warrant expires.
    pub expiry_epoch_ms: u64,

    /// Ed25519 signature by the Kernel.
    pub kernel_sig: [u8; 64],

    /// Public key that produced `kernel_sig`.
    pub kernel_pub: [u8; 32],
}

impl KernelWarrant {
    /// Returns the message bytes that the Kernel signs for this warrant.
    ///
    /// Wire format:
    /// `warrant_id || sha256(scope_cbor) || expiry_epoch_ms_be`
    pub fn signing_message(&self) -> Vec<u8> {
        let scope_hash: [u8; 32] = Sha256::digest(&self.scope_cbor).into();
        let mut message = Vec::with_capacity(32 + 32 + 8);
        message.extend_from_slice(&self.id);
        message.extend_from_slice(&scope_hash);
        message.extend_from_slice(&self.expiry_epoch_ms.to_be_bytes());
        message
    }

    /// Validate expiry and Ed25519 signature for the warrant.
    pub fn validate_at(&self, epoch_ms: u64) -> Result<(), PoGEError> {
        if epoch_ms > self.expiry_epoch_ms {
            return Err(PoGEError::WarrantExpired);
        }
        let verifying_key = VerifyingKey::from_bytes(&self.kernel_pub)
            .map_err(|_| PoGEError::WarrantSignatureInvalid)?;
        let signature = Signature::from_bytes(&self.kernel_sig);
        verifying_key
            .verify(&self.signing_message(), &signature)
            .map_err(|_| PoGEError::WarrantSignatureInvalid)
    }
}

// ---------------------------------------------------------------------------
// HostCallKind
// ---------------------------------------------------------------------------

/// Enumerates every category of Wasm/host boundary crossing.
///
/// Numeric discriminants are **stable and MUST NOT be reordered**; new
/// variants are appended only.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum HostCallKind {
    /// LLM inference call (prompt in, completion out).
    LlmInference = 0x01,
    /// Filesystem read: path → bytes.
    FsRead = 0x02,
    /// Filesystem write: path + bytes → ack.
    FsWrite = 0x03,
    /// HTTP/HTTPS fetch: request → response.
    WebFetch = 0x04,
    /// High-resolution wall clock read: () → epoch_ms.
    ClockNow = 0x05,
    /// Cryptographically secure random bytes: len → bytes.
    RngBytes = 0x06,
    /// Structured key-value store get: key → value.
    KvGet = 0x07,
    /// Structured key-value store put: key + value → ack.
    KvPut = 0x08,
    /// Sub-agent spawn: descriptor → agent_id.
    AgentSpawn = 0x09,
    /// Sub-agent join/result retrieval: agent_id → result_bytes.
    AgentJoin = 0x0A,
    /// Log emission: level + message → ack.
    LogEmit = 0x0B,
    /// Metric emission: name + value → ack.
    MetricEmit = 0x0C,
    /// Read bounded host diagnostics such as uname and OS release metadata.
    SystemInfo = 0x0D,
    /// Catch-all for extension host functions not yet enumerated.
    Extension = 0xFF,
}

impl HostCallKind {
    /// Returns the 1-byte discriminant used in domain-separated hashing.
    #[inline(always)]
    pub fn as_byte(self) -> u8 {
        self as u8
    }
}

// ---------------------------------------------------------------------------
// HostCallEvent
// ---------------------------------------------------------------------------

/// The raw, pre-digest record of a single host-call crossing.
///
/// `input_bytes` and `output_bytes` are borrowed slices; this struct holds
/// no heap allocation of its own.
#[derive(Clone, Debug)]
pub struct HostCallEvent<'a> {
    /// Category of host-call.
    pub kind: HostCallKind,

    /// Monotonically increasing counter within this governed session (starts at 0).
    pub sequence: u32,

    /// 32-byte governing Warrant ID.
    pub warrant_id: [u8; 32],

    /// UTC milliseconds at the moment the host-call was dispatched (pre-call).
    pub dispatch_epoch_ms: u64,

    /// Canonical byte representation of the call's input arguments.
    pub input_bytes: &'a [u8],

    /// Canonical byte representation of the call's output/return value.
    pub output_bytes: &'a [u8],

    /// `true` if the host-call resulted in an error.
    pub is_error: bool,
}

// ---------------------------------------------------------------------------
// HostCallReceipt
// ---------------------------------------------------------------------------

/// A 32-byte SHA-256 digest representing one verified host-call event.
///
/// Receipts are deterministic: identical [`HostCallEvent`] fields always
/// produce the same receipt.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct HostCallReceipt(pub [u8; 32]);

impl HostCallReceipt {
    /// The raw 32 bytes.
    #[inline(always)]
    pub fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }

    /// Returns the receipt as a lowercase hex string (64 chars) for logging.
    pub fn to_hex(&self) -> String {
        hex::encode(self.0)
    }
}

// ---------------------------------------------------------------------------
// PoGETrace
// ---------------------------------------------------------------------------

/// Maximum receipts in a single governed session (≈ 2 MiB at 32 B/receipt).
pub const MAX_TRACE_RECEIPTS: usize = 65_535; // u16::MAX

/// An ordered, bounded collection of [`HostCallReceipt`]s produced during a
/// single governed execution session.
#[derive(Debug)]
pub struct PoGETrace {
    /// Pre-allocated fixed-capacity buffer.
    receipts: Vec<HostCallReceipt>,

    /// Epoch ms of the first recorded receipt. Set on first push.
    pub epoch_start_ms: Option<u64>,

    /// Epoch ms of the most recently recorded receipt.
    pub epoch_end_ms: Option<u64>,
}

impl PoGETrace {
    /// Allocate the trace buffer, reserving the full memory budget upfront.
    pub fn new() -> Self {
        Self {
            receipts: Vec::with_capacity(MAX_TRACE_RECEIPTS),
            epoch_start_ms: None,
            epoch_end_ms: None,
        }
    }

    /// Append a receipt. Returns `Err(TraceOverflow)` if capacity is exhausted.
    pub fn push(&mut self, receipt: HostCallReceipt, epoch_ms: u64) -> Result<(), PoGEError> {
        if self.receipts.len() >= MAX_TRACE_RECEIPTS {
            return Err(PoGEError::TraceOverflow);
        }
        if self.epoch_start_ms.is_none() {
            self.epoch_start_ms = Some(epoch_ms);
        }
        self.epoch_end_ms = Some(epoch_ms);
        self.receipts.push(receipt);
        Ok(())
    }

    /// Number of receipts currently stored.
    pub fn len(&self) -> usize {
        self.receipts.len()
    }

    /// Returns `true` if no receipts have been recorded yet.
    pub fn is_empty(&self) -> bool {
        self.receipts.is_empty()
    }

    /// Read-only slice for Merkle tree construction.
    pub fn as_slice(&self) -> &[HostCallReceipt] {
        &self.receipts
    }
}

impl Default for PoGETrace {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Domain separation tags (RFC-MERIDIAN-0001 §5.1)
// ---------------------------------------------------------------------------

/// Domain tag for receipt (host-call event) hashing.
pub const RECEIPT_TAG: &[u8] = b"POGE_RECEIPT_v1\x00";

/// Domain tag prepended before hashing Merkle leaf nodes.
pub const MERKLE_LEAF_TAG: &[u8] = b"POGE_MERKLE_LEAF_v1\x00";

/// Domain tag prepended before hashing Merkle internal branch nodes.
pub const MERKLE_BRANCH_TAG: &[u8] = b"POGE_MERKLE_BRANCH_v1\x00";

// ---------------------------------------------------------------------------
// PoGEMerkleTree
// ---------------------------------------------------------------------------

/// A complete binary Merkle tree whose leaves are [`HostCallReceipt`]s.
///
/// ## Construction Algorithm (RFC-MERIDIAN-0001 §5.3)
/// 1. Leaves: `SHA-256(MERKLE_LEAF_TAG || receipt_bytes)`.
/// 2. Odd leaf count: last leaf duplicated (Bitcoin/Ethereum convention).
/// 3. Internal nodes: `SHA-256(MERKLE_BRANCH_TAG || left || right)`.
/// 4. Tree is stored flat in 1-indexed breadth-first order; root at index 1.
pub struct PoGEMerkleTree {
    /// Flat 1-indexed node array (index 0 unused). Root at index 1.
    nodes: Vec<[u8; 32]>,
    /// Number of padded leaf slots (next power-of-two ≥ receipt count).
    pub leaf_count: usize,
}

impl PoGEMerkleTree {
    /// Build a Merkle tree from an ordered receipt slice.
    ///
    /// # Panics
    /// Panics if `receipts` is empty; callers must guard against empty traces.
    pub fn build(receipts: &[HostCallReceipt]) -> Self {
        assert!(
            !receipts.is_empty(),
            "cannot build Merkle tree from empty trace"
        );

        // Pad to next power-of-two for a complete binary tree.
        let padded = receipts.len().next_power_of_two();
        // 1-indexed flat array: node 1 = root, leaves at [padded .. 2*padded].
        let total_slots = 2 * padded + 1;
        let mut nodes: Vec<[u8; 32]> = vec![[0u8; 32]; total_slots];

        // Hash leaves into slots [padded .. padded + receipts.len()].
        for (i, receipt) in receipts.iter().enumerate() {
            nodes[padded + i] = Self::hash_leaf(receipt);
        }
        // Duplicate last leaf for any odd-padding slots.
        let last_leaf = nodes[padded + receipts.len() - 1];
        for i in receipts.len()..padded {
            nodes[padded + i] = last_leaf;
        }
        // Build internal nodes bottom-up (from level above leaves to root).
        for i in (1..padded).rev() {
            let left = nodes[2 * i];
            let right = nodes[2 * i + 1];
            nodes[i] = Self::hash_branch(&left, &right);
        }

        Self {
            nodes,
            leaf_count: padded,
        }
    }

    /// Returns the 32-byte Merkle root.
    #[inline(always)]
    pub fn root(&self) -> [u8; 32] {
        self.nodes[1]
    }

    /// Compute a domain-separated leaf hash.
    fn hash_leaf(receipt: &HostCallReceipt) -> [u8; 32] {
        let mut h = Sha256::new();
        h.update(MERKLE_LEAF_TAG);
        h.update(receipt.as_bytes());
        h.finalize().into()
    }

    /// Compute a domain-separated branch hash.
    fn hash_branch(left: &[u8; 32], right: &[u8; 32]) -> [u8; 32] {
        let mut h = Sha256::new();
        h.update(MERKLE_BRANCH_TAG);
        h.update(left);
        h.update(right);
        h.finalize().into()
    }

    /// Generate a Merkle inclusion proof for the receipt at `index`.
    ///
    /// Returns sibling hashes leaf-to-root, compatible with OpenZeppelin's
    /// `MerkleProof.verify()` convention.
    pub fn proof_for(&self, index: usize) -> Vec<[u8; 32]> {
        let mut proof = Vec::new();
        let mut pos = self.leaf_count + index;
        while pos > 1 {
            let sibling = if pos % 2 == 0 { pos + 1 } else { pos - 1 };
            proof.push(self.nodes[sibling]);
            pos /= 2;
        }
        proof
    }
}

// ---------------------------------------------------------------------------
// PoGEAuditRoot
// ---------------------------------------------------------------------------

/// The finalized, on-chain-settleable record for one governed execution session.
#[derive(Clone, Debug)]
pub struct PoGEAuditRoot {
    /// 32-byte Merkle root of the full execution trace.
    pub merkle_root: [u8; 32],

    /// 32-byte Kernel Warrant ID that governed this session.
    pub warrant_id: [u8; 32],

    /// Total number of host-call receipts in the trace (before Merkle padding).
    pub trace_len: u32,

    /// UTC milliseconds of the first recorded host-call.
    pub epoch_start_ms: u64,

    /// UTC milliseconds of the last recorded host-call.
    pub epoch_end_ms: u64,

    /// SHA-256 of the Wasm guest module bytes (module-level non-repudiation).
    pub module_digest: [u8; 32],

    /// Human-readable session label for off-chain indexing (max 64 bytes).
    pub session_label: String,
}

impl PoGEAuditRoot {
    /// Returns the Merkle root as a 0x-prefixed hex string (66 chars).
    pub fn merkle_root_hex(&self) -> String {
        format!("0x{}", hex::encode(self.merkle_root))
    }

    /// Returns a compact witness digest that binds the finalized audit root.
    pub fn witness_digest(&self) -> [u8; 32] {
        let mut hasher = Sha256::new();
        hasher.update(b"POGE_ZK_WITNESS_v1\x00");
        hasher.update(self.merkle_root);
        hasher.update(self.warrant_id);
        hasher.update(self.trace_len.to_be_bytes());
        hasher.update(self.epoch_start_ms.to_be_bytes());
        hasher.update(self.epoch_end_ms.to_be_bytes());
        hasher.update(self.module_digest);
        hasher.update((self.session_label.len() as u32).to_be_bytes());
        hasher.update(self.session_label.as_bytes());
        hasher.finalize().into()
    }

    pub fn witness_digest_hex(&self) -> String {
        format!("0x{}", hex::encode(self.witness_digest()))
    }
}

// ---------------------------------------------------------------------------
// PoGEInterceptor
// ---------------------------------------------------------------------------

/// Central mutable object for one governed execution session.
///
/// # Lifecycle
/// 1. `PoGEInterceptor::new(warrant, module_digest, label)`
/// 2. Call `record_event()` from each Wasmtime host-function shim.
/// 3. Call `finalize()` to obtain the [`PoGEAuditRoot`].
#[derive(Debug)]
pub struct PoGEInterceptor {
    warrant: KernelWarrant,
    module_digest: [u8; 32],
    session_label: String,
    trace: PoGETrace,
    sequence: u32,
}

impl PoGEInterceptor {
    /// Create a new interceptor for a governed session.
    pub fn new(
        warrant: KernelWarrant,
        module_digest: [u8; 32],
        session_label: impl Into<String>,
    ) -> Self {
        Self {
            warrant,
            module_digest,
            session_label: session_label.into(),
            trace: PoGETrace::new(),
            sequence: 0,
        }
    }

    /// Create a new interceptor only after warrant validation succeeds.
    pub fn new_validated(
        warrant: KernelWarrant,
        module_digest: [u8; 32],
        session_label: impl Into<String>,
        now_epoch_ms: u64,
    ) -> Result<Self, PoGEError> {
        warrant.validate_at(now_epoch_ms)?;
        Ok(Self::new(warrant, module_digest, session_label))
    }

    /// Compute the receipt for a host-call event and append it to the trace.
    ///
    /// Hot-path entry point called from every Wasmtime shim.
    pub fn record_event(
        &mut self,
        kind: HostCallKind,
        dispatch_epoch_ms: u64,
        input_bytes: &[u8],
        output_bytes: &[u8],
        is_error: bool,
    ) -> Result<HostCallReceipt, PoGEError> {
        if dispatch_epoch_ms > self.warrant.expiry_epoch_ms {
            return Err(PoGEError::WarrantExpired);
        }
        let event = HostCallEvent {
            kind,
            sequence: self.sequence,
            warrant_id: self.warrant.id,
            dispatch_epoch_ms,
            input_bytes,
            output_bytes,
            is_error,
        };
        let receipt = Self::receipt_for(&event);
        self.trace.push(receipt, dispatch_epoch_ms)?;
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or(PoGEError::TraceOverflow)?;
        Ok(receipt)
    }

    /// Number of events recorded so far.
    pub fn event_count(&self) -> usize {
        self.trace.len()
    }

    /// Finalize the session: build the Merkle tree and return the [`PoGEAuditRoot`].
    ///
    /// Consumes the interceptor; the Merkle tree allocation is freed after
    /// root extraction.
    pub fn finalize(self) -> Result<PoGEAuditRoot, PoGEError> {
        if self.trace.is_empty() {
            return Err(PoGEError::EmptyTrace);
        }
        let tree = PoGEMerkleTree::build(self.trace.as_slice());
        let root = tree.root();
        // `tree` drops here; ~4 MiB allocation freed.
        Ok(PoGEAuditRoot {
            merkle_root: root,
            warrant_id: self.warrant.id,
            trace_len: self.trace.len() as u32,
            epoch_start_ms: self.trace.epoch_start_ms.unwrap_or(0),
            epoch_end_ms: self.trace.epoch_end_ms.unwrap_or(0),
            module_digest: self.module_digest,
            session_label: self.session_label,
        })
    }

    /// Compute the 32-byte SHA-256 receipt for a single [`HostCallEvent`].
    ///
    /// Uses a streaming hasher — no concatenated buffer is ever allocated.
    ///
    /// ## Wire format (RFC-MERIDIAN-0001 §5.2)
    /// ```text
    /// "POGE_RECEIPT_v1\x00"  -- 16 B, domain tag
    /// || kind_byte            -- 1 B
    /// || seq_be               -- 4 B, big-endian u32
    /// || warrant_id           -- 32 B
    /// || epoch_ms_be          -- 8 B, big-endian u64
    /// || len(input)_be        -- 4 B, big-endian u32 (length-prefix framing)
    /// || input                -- variable
    /// || len(output)_be       -- 4 B, big-endian u32
    /// || output               -- variable
    /// || is_error_byte        -- 1 B, 0x00 or 0x01
    /// ```
    pub fn receipt_for(event: &HostCallEvent<'_>) -> HostCallReceipt {
        let mut h = Sha256::new();
        h.update(RECEIPT_TAG);
        h.update([event.kind.as_byte()]);
        h.update(event.sequence.to_be_bytes());
        h.update(event.warrant_id);
        h.update(event.dispatch_epoch_ms.to_be_bytes());
        h.update((event.input_bytes.len() as u32).to_be_bytes());
        h.update(event.input_bytes);
        h.update((event.output_bytes.len() as u32).to_be_bytes());
        h.update(event.output_bytes);
        h.update([event.is_error as u8]);
        HostCallReceipt(h.finalize().into())
    }
}

// ---------------------------------------------------------------------------
// Proof Aggregation
// ---------------------------------------------------------------------------

/// A leaf in a proof aggregation tree — represents one finalized session proof.
#[derive(Clone, Debug)]
pub struct ProofLeaf {
    pub merkle_root: [u8; 32],
    pub witness_digest: [u8; 32],
    pub trace_len: u32,
    pub session_label: String,
}

impl ProofLeaf {
    fn hash(&self) -> [u8; 32] {
        let mut hasher = Sha256::new();
        hasher.update(b"POGE_AGG_LEAF_v1\x00");
        hasher.update(self.merkle_root);
        hasher.update(self.witness_digest);
        hasher.update(self.trace_len.to_be_bytes());
        hasher.update((self.session_label.len() as u32).to_be_bytes());
        hasher.update(self.session_label.as_bytes());
        hasher.finalize().into()
    }
}

/// Aggregated proof over multiple session proofs.
#[derive(Clone, Debug)]
pub struct AggregateProof {
    pub aggregate_root: [u8; 32],
    pub leaf_count: usize,
    pub total_trace_len: u32,
    leaf_hashes: Vec<[u8; 32]>,
}

impl AggregateProof {
    pub fn aggregate_root_hex(&self) -> String {
        format!("0x{}", hex::encode(self.aggregate_root))
    }

    /// Check if a leaf is included in this aggregate.
    pub fn contains_leaf(&self, leaf: &ProofLeaf) -> bool {
        let h = leaf.hash();
        self.leaf_hashes.contains(&h)
    }
}

/// Aggregate multiple proof leaves into a single aggregate root.
///
/// The aggregate root is a Merkle tree over the leaf hashes.
/// Order matters — the same leaves in a different order produce a different root.
pub fn aggregate_proofs(leaves: &[ProofLeaf]) -> Result<AggregateProof, PoGEError> {
    if leaves.is_empty() {
        return Ok(AggregateProof {
            aggregate_root: [0u8; 32],
            leaf_count: 0,
            total_trace_len: 0,
            leaf_hashes: Vec::new(),
        });
    }
    let leaf_hashes: Vec<[u8; 32]> = leaves.iter().map(|l| l.hash()).collect();
    let total_trace_len: u32 = leaves.iter().map(|l| l.trace_len).sum();

    // Build Merkle tree over leaf hashes
    let mut current = leaf_hashes.clone();
    while current.len() > 1 {
        let mut next = Vec::new();
        for chunk in current.chunks(2) {
            if chunk.len() == 2 {
                let mut hasher = Sha256::new();
                hasher.update(chunk[0]);
                hasher.update(chunk[1]);
                next.push(hasher.finalize().into());
            } else {
                next.push(chunk[0]);
            }
        }
        current = next;
    }

    Ok(AggregateProof {
        aggregate_root: current[0],
        leaf_count: leaves.len(),
        total_trace_len,
        leaf_hashes,
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signature, Signer, SigningKey};

    fn warrant_message(id: [u8; 32], scope_cbor: &[u8], expiry_epoch_ms: u64) -> Vec<u8> {
        let scope_hash: [u8; 32] = Sha256::digest(scope_cbor).into();
        let mut message = Vec::with_capacity(32 + 32 + 8);
        message.extend_from_slice(&id);
        message.extend_from_slice(&scope_hash);
        message.extend_from_slice(&expiry_epoch_ms.to_be_bytes());
        message
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    fn make_warrant(id: [u8; 32]) -> KernelWarrant {
        KernelWarrant {
            id,
            scope_cbor: vec![],
            expiry_epoch_ms: u64::MAX,
            kernel_sig: [0u8; 64],
            kernel_pub: [0u8; 32],
        }
    }

    fn zero_warrant() -> KernelWarrant {
        make_warrant([0u8; 32])
    }

    fn sequential_warrant() -> KernelWarrant {
        let mut id = [0u8; 32];
        for (i, b) in id.iter_mut().enumerate() {
            *b = i as u8;
        }
        make_warrant(id)
    }

    fn signed_warrant(expiry_epoch_ms: u64) -> KernelWarrant {
        let seed = [7u8; 32];
        let signer = SigningKey::from_bytes(&seed);
        let mut id = [0u8; 32];
        for (index, slot) in id.iter_mut().enumerate() {
            *slot = (index as u8).wrapping_mul(3).wrapping_add(1);
        }
        let scope_cbor = vec![0xA1, 0x63, b'w', b'e', b'b', 0xF5];
        let signature: Signature = signer.sign(&warrant_message(id, &scope_cbor, expiry_epoch_ms));
        KernelWarrant {
            id,
            scope_cbor,
            expiry_epoch_ms,
            kernel_sig: signature.to_bytes(),
            kernel_pub: signer.verifying_key().to_bytes(),
        }
    }

    // -----------------------------------------------------------------------
    // HostCallReceipt
    // -----------------------------------------------------------------------

    #[test]
    fn receipt_deterministic() {
        let warrant = zero_warrant();
        let event = HostCallEvent {
            kind: HostCallKind::LlmInference,
            sequence: 0,
            warrant_id: warrant.id,
            dispatch_epoch_ms: 1_700_000_000_000,
            input_bytes: b"hello",
            output_bytes: b"world",
            is_error: false,
        };
        let r1 = PoGEInterceptor::receipt_for(&event);
        let r2 = PoGEInterceptor::receipt_for(&event);
        assert_eq!(r1, r2, "identical events must produce identical receipts");
    }

    #[test]
    fn receipt_is_32_bytes() {
        let event = HostCallEvent {
            kind: HostCallKind::FsRead,
            sequence: 7,
            warrant_id: [0xAB; 32],
            dispatch_epoch_ms: 0,
            input_bytes: b"/etc/passwd",
            output_bytes: b"root:x:0:0",
            is_error: false,
        };
        let r = PoGEInterceptor::receipt_for(&event);
        assert_eq!(r.as_bytes().len(), 32);
    }

    #[test]
    fn receipt_changes_on_every_field() {
        let base = HostCallEvent {
            kind: HostCallKind::WebFetch,
            sequence: 1,
            warrant_id: [0u8; 32],
            dispatch_epoch_ms: 1_000,
            input_bytes: b"GET /",
            output_bytes: b"200 OK",
            is_error: false,
        };

        let r_base = PoGEInterceptor::receipt_for(&base);

        // Change kind
        let mut e = base.clone();
        e.kind = HostCallKind::FsWrite;
        assert_ne!(PoGEInterceptor::receipt_for(&e), r_base, "kind");

        // Change sequence
        let mut e = base.clone();
        e.sequence = 2;
        assert_ne!(PoGEInterceptor::receipt_for(&e), r_base, "sequence");

        // Change warrant_id
        let mut e = base.clone();
        e.warrant_id = [0xFF; 32];
        assert_ne!(PoGEInterceptor::receipt_for(&e), r_base, "warrant_id");

        // Change epoch
        let mut e = base.clone();
        e.dispatch_epoch_ms = 2_000;
        assert_ne!(PoGEInterceptor::receipt_for(&e), r_base, "epoch_ms");

        // Change input
        let mut e = base.clone();
        e.input_bytes = b"POST /";
        assert_ne!(PoGEInterceptor::receipt_for(&e), r_base, "input_bytes");

        // Change output
        let mut e = base.clone();
        e.output_bytes = b"404 Not Found";
        assert_ne!(PoGEInterceptor::receipt_for(&e), r_base, "output_bytes");

        // Change is_error flag
        let mut e = base.clone();
        e.is_error = true;
        assert_ne!(PoGEInterceptor::receipt_for(&e), r_base, "is_error");
    }

    #[test]
    fn receipt_length_prefix_prevents_collision() {
        // Without length-prefix framing "ab"||"cd" == "a"||"bcd".
        // With framing they must differ.
        let make = |input: &'static [u8], output: &'static [u8]| {
            PoGEInterceptor::receipt_for(&HostCallEvent {
                kind: HostCallKind::KvGet,
                sequence: 0,
                warrant_id: [0u8; 32],
                dispatch_epoch_ms: 0,
                input_bytes: input,
                output_bytes: output,
                is_error: false,
            })
        };
        assert_ne!(make(b"ab", b"cd"), make(b"a", b"bcd"));
        assert_ne!(make(b"", b"abcd"), make(b"ab", b"cd"));
    }

    #[test]
    fn receipt_to_hex_is_64_chars() {
        let r = PoGEInterceptor::receipt_for(&HostCallEvent {
            kind: HostCallKind::LogEmit,
            sequence: 0,
            warrant_id: [0u8; 32],
            dispatch_epoch_ms: 0,
            input_bytes: b"test",
            output_bytes: b"",
            is_error: false,
        });
        let h = r.to_hex();
        assert_eq!(h.len(), 64);
        assert!(h.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn receipt_known_vector() {
        // Pre-computed reference value — guards against accidental wire-format drift.
        //
        // Fields:
        //   kind          = LlmInference (0x01)
        //   sequence      = 0x00000000
        //   warrant_id    = [0u8; 32]
        //   epoch_ms      = 0x0000000000000000
        //   input         = b"prompt" (len=6)
        //   output        = b"result" (len=6)
        //   is_error      = 0x00
        let event = HostCallEvent {
            kind: HostCallKind::LlmInference,
            sequence: 0,
            warrant_id: [0u8; 32],
            dispatch_epoch_ms: 0,
            input_bytes: b"prompt",
            output_bytes: b"result",
            is_error: false,
        };
        let receipt = PoGEInterceptor::receipt_for(&event);

        // Compute expected independently using the same algorithm.
        let mut h = Sha256::new();
        h.update(b"POGE_RECEIPT_v1\x00");
        h.update([0x01u8]); // kind
        h.update(0u32.to_be_bytes()); // sequence
        h.update([0u8; 32]); // warrant_id
        h.update(0u64.to_be_bytes()); // epoch_ms
        h.update(6u32.to_be_bytes()); // len(input)
        h.update(b"prompt");
        h.update(6u32.to_be_bytes()); // len(output)
        h.update(b"result");
        h.update([0x00u8]); // is_error
        let expected: [u8; 32] = h.finalize().into();

        assert_eq!(receipt.0, expected, "known-vector mismatch");
    }

    // -----------------------------------------------------------------------
    // PoGETrace
    // -----------------------------------------------------------------------

    #[test]
    fn trace_starts_empty() {
        let t = PoGETrace::new();
        assert!(t.is_empty());
        assert_eq!(t.len(), 0);
        assert!(t.epoch_start_ms.is_none());
        assert!(t.epoch_end_ms.is_none());
    }

    #[test]
    fn trace_push_and_epoch_tracking() {
        let mut t = PoGETrace::new();
        let r = HostCallReceipt([1u8; 32]);
        t.push(r, 1000).unwrap();
        assert_eq!(t.len(), 1);
        assert_eq!(t.epoch_start_ms, Some(1000));
        assert_eq!(t.epoch_end_ms, Some(1000));

        let r2 = HostCallReceipt([2u8; 32]);
        t.push(r2, 2000).unwrap();
        assert_eq!(t.len(), 2);
        assert_eq!(t.epoch_start_ms, Some(1000), "start must not change");
        assert_eq!(t.epoch_end_ms, Some(2000));
    }

    #[test]
    fn trace_overflow_returns_error() {
        let mut t = PoGETrace::new();
        // Fill to the limit.
        for i in 0..MAX_TRACE_RECEIPTS {
            t.push(HostCallReceipt([(i % 256) as u8; 32]), i as u64)
                .unwrap();
        }
        // One more must fail.
        let result = t.push(HostCallReceipt([0u8; 32]), 99_999);
        assert_eq!(result, Err(PoGEError::TraceOverflow));
    }

    // -----------------------------------------------------------------------
    // PoGEMerkleTree
    // -----------------------------------------------------------------------

    fn make_receipt(seed: u8) -> HostCallReceipt {
        HostCallReceipt([seed; 32])
    }

    #[test]
    fn merkle_single_leaf_root_is_leaf_hash() {
        // n=1 → next_power_of_two=1 → padded=1 → no internal nodes.
        // Root (nodes[1]) is the leaf hash itself.
        let r = make_receipt(0xAA);
        let tree = PoGEMerkleTree::build(&[r]);
        assert_eq!(tree.leaf_count, 1);
        let root = tree.root();

        let mut h = Sha256::new();
        h.update(MERKLE_LEAF_TAG);
        h.update(r.as_bytes());
        let expected: [u8; 32] = h.finalize().into();

        assert_eq!(root, expected);
    }

    #[test]
    fn merkle_three_leaves_duplicates_last() {
        // n=3 → padded=4. Leaf 4 (index 3) duplicates leaf 3 (index 2).
        let r0 = make_receipt(0x01);
        let r1 = make_receipt(0x02);
        let r2 = make_receipt(0x03);
        let tree = PoGEMerkleTree::build(&[r0, r1, r2]);
        assert_eq!(tree.leaf_count, 4);

        // Compute manually.
        let lh = |r: &HostCallReceipt| -> [u8; 32] {
            let mut h = Sha256::new();
            h.update(MERKLE_LEAF_TAG);
            h.update(r.as_bytes());
            h.finalize().into()
        };
        let bh = |l: &[u8; 32], r: &[u8; 32]| -> [u8; 32] {
            let mut h = Sha256::new();
            h.update(MERKLE_BRANCH_TAG);
            h.update(l);
            h.update(r);
            h.finalize().into()
        };

        let l0 = lh(&r0);
        let l1 = lh(&r1);
        let l2 = lh(&r2);
        let l3 = l2; // duplicated last leaf
        let n2 = bh(&l0, &l1);
        let n3 = bh(&l2, &l3);
        let expected_root = bh(&n2, &n3);

        assert_eq!(tree.root(), expected_root);
    }

    #[test]
    fn merkle_two_leaves_root_correct() {
        let r0 = make_receipt(0x01);
        let r1 = make_receipt(0x02);
        let tree = PoGEMerkleTree::build(&[r0, r1]);

        let leaf0 = {
            let mut h = Sha256::new();
            h.update(MERKLE_LEAF_TAG);
            h.update(r0.as_bytes());
            let out: [u8; 32] = h.finalize().into();
            out
        };
        let leaf1 = {
            let mut h = Sha256::new();
            h.update(MERKLE_LEAF_TAG);
            h.update(r1.as_bytes());
            let out: [u8; 32] = h.finalize().into();
            out
        };
        let expected = {
            let mut h = Sha256::new();
            h.update(MERKLE_BRANCH_TAG);
            h.update(leaf0);
            h.update(leaf1);
            let out: [u8; 32] = h.finalize().into();
            out
        };

        assert_eq!(tree.root(), expected);
    }

    #[test]
    fn merkle_root_changes_when_receipt_changes() {
        let receipts_a = [make_receipt(1), make_receipt(2), make_receipt(3)];
        let mut receipts_b = receipts_a;
        receipts_b[1] = make_receipt(0xFF);

        let root_a = PoGEMerkleTree::build(&receipts_a).root();
        let root_b = PoGEMerkleTree::build(&receipts_b).root();
        assert_ne!(root_a, root_b);
    }

    #[test]
    fn merkle_root_changes_when_order_changes() {
        let r0 = make_receipt(0x10);
        let r1 = make_receipt(0x20);
        let root_fwd = PoGEMerkleTree::build(&[r0, r1]).root();
        let root_rev = PoGEMerkleTree::build(&[r1, r0]).root();
        assert_ne!(root_fwd, root_rev, "Merkle root must be order-sensitive");
    }

    #[test]
    fn merkle_root_is_32_bytes() {
        let receipts: Vec<HostCallReceipt> = (0u8..4).map(make_receipt).collect();
        let root = PoGEMerkleTree::build(&receipts).root();
        assert_eq!(root.len(), 32);
    }

    #[test]
    fn merkle_proof_for_every_leaf() {
        let receipts: Vec<HostCallReceipt> = (0u8..4).map(make_receipt).collect();
        let tree = PoGEMerkleTree::build(&receipts);
        // 4 leaves (padded=4): proof depth = log2(4) = 2 siblings.
        for i in 0..receipts.len() {
            let proof = tree.proof_for(i);
            assert_eq!(proof.len(), 2, "proof depth for 4 leaves should be 2");
        }
    }

    #[test]
    fn merkle_leaf_count_is_power_of_two() {
        for n in [1usize, 2, 3, 5, 7, 8, 9, 15, 16] {
            let receipts: Vec<HostCallReceipt> = (0..n).map(|i| make_receipt(i as u8)).collect();
            let tree = PoGEMerkleTree::build(&receipts);
            assert!(
                tree.leaf_count.is_power_of_two(),
                "leaf_count={} for n={} is not power-of-two",
                tree.leaf_count,
                n
            );
            assert!(tree.leaf_count >= n);
        }
    }

    // -----------------------------------------------------------------------
    // PoGEInterceptor (integration)
    // -----------------------------------------------------------------------

    #[test]
    fn interceptor_empty_finalize_returns_error() {
        let w = zero_warrant();
        let interceptor = PoGEInterceptor::new(w, [0u8; 32], "test");
        assert!(
            matches!(interceptor.finalize(), Err(PoGEError::EmptyTrace)),
            "expected EmptyTrace error"
        );
    }

    #[test]
    fn interceptor_single_event_produces_audit_root() {
        let w = sequential_warrant();
        let module_digest = [0xBE; 32];
        let mut interceptor = PoGEInterceptor::new(w.clone(), module_digest, "session-alpha");

        let receipt = interceptor
            .record_event(
                HostCallKind::LlmInference,
                1_700_000_000_000,
                b"What is 2+2?",
                b"4",
                false,
            )
            .expect("record_event should succeed");

        assert_eq!(receipt.as_bytes().len(), 32);
        assert_eq!(interceptor.event_count(), 1);

        let audit_root = interceptor.finalize().expect("finalize should succeed");

        assert_eq!(audit_root.warrant_id, w.id);
        assert_eq!(audit_root.trace_len, 1);
        assert_eq!(audit_root.epoch_start_ms, 1_700_000_000_000);
        assert_eq!(audit_root.epoch_end_ms, 1_700_000_000_000);
        assert_eq!(audit_root.module_digest, module_digest);
        assert_eq!(audit_root.session_label, "session-alpha");
        assert_eq!(audit_root.merkle_root.len(), 32);
    }

    #[test]
    fn interceptor_sequence_increments() {
        let w = zero_warrant();
        let mut interceptor = PoGEInterceptor::new(w, [0u8; 32], "seq-test");

        // Three events; each uses a different sequence number, so receipts differ.
        let mut receipts = Vec::new();
        for i in 0u64..3 {
            let r = interceptor
                .record_event(HostCallKind::KvGet, i * 1000, b"key", b"val", false)
                .unwrap();
            receipts.push(r);
        }
        // All three receipts must be distinct (sequence numbers differ).
        assert_ne!(receipts[0], receipts[1]);
        assert_ne!(receipts[1], receipts[2]);
        assert_ne!(receipts[0], receipts[2]);
    }

    #[test]
    fn interceptor_epoch_range_tracked() {
        let w = zero_warrant();
        let mut interceptor = PoGEInterceptor::new(w, [0u8; 32], "epoch-test");

        interceptor
            .record_event(HostCallKind::ClockNow, 500, b"", b"500", false)
            .unwrap();
        interceptor
            .record_event(HostCallKind::ClockNow, 1500, b"", b"1500", false)
            .unwrap();
        interceptor
            .record_event(HostCallKind::ClockNow, 3000, b"", b"3000", false)
            .unwrap();

        let root = interceptor.finalize().unwrap();
        assert_eq!(root.epoch_start_ms, 500);
        assert_eq!(root.epoch_end_ms, 3000);
        assert_eq!(root.trace_len, 3);
    }

    #[test]
    fn interceptor_audit_root_hex_prefixed() {
        let w = zero_warrant();
        let mut interceptor = PoGEInterceptor::new(w, [0u8; 32], "hex-test");
        interceptor
            .record_event(HostCallKind::MetricEmit, 0, b"latency", b"42", false)
            .unwrap();
        let root = interceptor.finalize().unwrap();
        let hex = root.merkle_root_hex();
        assert!(hex.starts_with("0x"), "should have 0x prefix");
        assert_eq!(hex.len(), 66, "0x + 64 hex chars");
    }

    #[test]
    fn interceptor_merkle_root_deterministic_across_runs() {
        let build_root = || {
            let w = make_warrant([0xDE; 32]);
            let mut interceptor = PoGEInterceptor::new(w, [0xAD; 32], "determ");
            interceptor
                .record_event(HostCallKind::FsRead, 100, b"path", b"data", false)
                .unwrap();
            interceptor
                .record_event(HostCallKind::FsWrite, 200, b"path", b"ack", false)
                .unwrap();
            interceptor.finalize().unwrap().merkle_root
        };

        let root1 = build_root();
        let root2 = build_root();
        assert_eq!(root1, root2, "Merkle root must be fully deterministic");
    }

    #[test]
    fn interceptor_different_warrant_ids_produce_different_roots() {
        let build_root = |warrant_id: [u8; 32]| {
            let w = make_warrant(warrant_id);
            let mut interceptor = PoGEInterceptor::new(w, [0u8; 32], "wid-test");
            interceptor
                .record_event(HostCallKind::AgentSpawn, 0, b"desc", b"agent-1", false)
                .unwrap();
            interceptor.finalize().unwrap().merkle_root
        };

        let root_a = build_root([0u8; 32]);
        let root_b = build_root([1u8; 32]);
        assert_ne!(
            root_a, root_b,
            "different warrant IDs must produce different roots"
        );
    }

    #[test]
    fn interceptor_error_events_produce_distinct_receipts() {
        let make = |is_error: bool| {
            PoGEInterceptor::receipt_for(&HostCallEvent {
                kind: HostCallKind::WebFetch,
                sequence: 0,
                warrant_id: [0u8; 32],
                dispatch_epoch_ms: 0,
                input_bytes: b"https://example.com",
                output_bytes: b"timeout",
                is_error,
            })
        };
        assert_ne!(make(false), make(true));
    }

    #[test]
    fn interceptor_multi_event_trace_non_empty_root() {
        let w = zero_warrant();
        let mut interceptor = PoGEInterceptor::new(w, [0u8; 32], "multi");
        for i in 0..10u64 {
            interceptor
                .record_event(
                    HostCallKind::KvPut,
                    i * 100,
                    format!("key-{}", i).as_bytes(),
                    b"ok",
                    false,
                )
                .unwrap();
        }
        let root = interceptor.finalize().unwrap();
        assert_eq!(root.trace_len, 10);
        assert_ne!(root.merkle_root, [0u8; 32]);
    }

    #[test]
    fn validated_interceptor_accepts_signed_warrant() {
        let warrant = signed_warrant(u64::MAX - 10);
        let mut interceptor =
            PoGEInterceptor::new_validated(warrant.clone(), [0x11; 32], "validated", 42)
                .expect("validated interceptor");
        interceptor
            .record_event(
                HostCallKind::SystemInfo,
                43,
                b"{}",
                br#"{"hostname":"loom"}"#,
                false,
            )
            .expect("record");
        let audit_root = interceptor.finalize().expect("finalize");
        assert_eq!(audit_root.warrant_id, warrant.id);
        assert_eq!(audit_root.trace_len, 1);
    }

    #[test]
    fn validated_interceptor_rejects_expired_warrant() {
        let warrant = signed_warrant(10);
        let error = PoGEInterceptor::new_validated(warrant, [0u8; 32], "expired", 11)
            .expect_err("expired warrant should fail");
        assert_eq!(error, PoGEError::WarrantExpired);
    }

    #[test]
    fn validated_interceptor_rejects_invalid_signature() {
        let mut warrant = signed_warrant(u64::MAX - 10);
        warrant.kernel_sig[0] ^= 0xFF;
        let error = PoGEInterceptor::new_validated(warrant, [0u8; 32], "invalid", 1)
            .expect_err("invalid signature should fail");
        assert_eq!(error, PoGEError::WarrantSignatureInvalid);
    }

    // -----------------------------------------------------------------------
    // PoGEError
    // -----------------------------------------------------------------------

    #[test]
    fn error_display_messages_non_empty() {
        let errors = [
            PoGEError::TraceOverflow,
            PoGEError::EmptyTrace,
            PoGEError::WarrantExpired,
            PoGEError::WarrantSignatureInvalid,
            PoGEError::SettlementFailed("rpc timeout".into()),
        ];
        for e in &errors {
            let msg = format!("{}", e);
            assert!(!msg.is_empty(), "error message should not be empty");
        }
    }

    // -----------------------------------------------------------------------
    // Proof Aggregation
    // -----------------------------------------------------------------------

    #[test]
    fn aggregate_proof_from_multiple_roots() {
        let roots = vec![
            ProofLeaf {
                merkle_root: [1u8; 32],
                witness_digest: [2u8; 32],
                trace_len: 5,
                session_label: "session_a".to_string(),
            },
            ProofLeaf {
                merkle_root: [3u8; 32],
                witness_digest: [4u8; 32],
                trace_len: 10,
                session_label: "session_b".to_string(),
            },
        ];
        let agg = aggregate_proofs(&roots).unwrap();
        assert_eq!(agg.leaf_count, 2);
        assert_eq!(agg.total_trace_len, 15);
        assert_ne!(agg.aggregate_root, [0u8; 32]);
    }

    #[test]
    fn aggregate_proof_is_deterministic() {
        let roots = vec![
            ProofLeaf {
                merkle_root: [1u8; 32],
                witness_digest: [2u8; 32],
                trace_len: 5,
                session_label: "a".to_string(),
            },
        ];
        let a1 = aggregate_proofs(&roots).unwrap();
        let a2 = aggregate_proofs(&roots).unwrap();
        assert_eq!(a1.aggregate_root, a2.aggregate_root);
    }

    #[test]
    fn aggregate_proof_changes_with_order() {
        let leaf_a = ProofLeaf {
            merkle_root: [1u8; 32],
            witness_digest: [2u8; 32],
            trace_len: 5,
            session_label: "a".to_string(),
        };
        let leaf_b = ProofLeaf {
            merkle_root: [3u8; 32],
            witness_digest: [4u8; 32],
            trace_len: 10,
            session_label: "b".to_string(),
        };
        let agg_ab = aggregate_proofs(&[leaf_a.clone(), leaf_b.clone()]).unwrap();
        let agg_ba = aggregate_proofs(&[leaf_b, leaf_a]).unwrap();
        assert_ne!(
            agg_ab.aggregate_root, agg_ba.aggregate_root,
            "order matters for aggregate root"
        );
    }

    #[test]
    fn aggregate_proof_empty_returns_zero_root() {
        let agg = aggregate_proofs(&[]).unwrap();
        assert_eq!(agg.aggregate_root, [0u8; 32]);
        assert_eq!(agg.leaf_count, 0);
    }

    #[test]
    fn aggregate_proof_hex_format() {
        let roots = vec![ProofLeaf {
            merkle_root: [0xABu8; 32],
            witness_digest: [0xCDu8; 32],
            trace_len: 1,
            session_label: "x".to_string(),
        }];
        let agg = aggregate_proofs(&roots).unwrap();
        let hex = agg.aggregate_root_hex();
        assert_eq!(hex.len(), 66); // 0x + 64 hex chars
        assert!(hex.starts_with("0x"));
    }

    #[test]
    fn verify_leaf_inclusion_in_aggregate() {
        let leaf = ProofLeaf {
            merkle_root: [1u8; 32],
            witness_digest: [2u8; 32],
            trace_len: 5,
            session_label: "a".to_string(),
        };
        let agg = aggregate_proofs(&[leaf.clone()]).unwrap();
        assert!(agg.contains_leaf(&leaf));
        let other = ProofLeaf {
            merkle_root: [99u8; 32],
            witness_digest: [100u8; 32],
            trace_len: 1,
            session_label: "z".to_string(),
        };
        assert!(!agg.contains_leaf(&other));
    }
}
