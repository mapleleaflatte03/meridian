# Meridian Proof of Governed Execution (PoGE) Protocol

**RFC-MERIDIAN-0001 · Status: DRAFT · Revision: 1.0.0**
**Author:** Meridian Cryptography Architecture Group
**Date:** 2026-03-27
**Implements:** Meridian Loom Runtime v0.1.16, Loom-Core Host-Call Boundary
**Target Chain:** Base Sepolia (EVM-compatible, Chain ID: 84532)

---

## Abstract

This document specifies the **Proof of Governed Execution (PoGE)** protocol: a cryptographic receipt system layered over the Meridian Loom Wasm runtime that produces a tamper-evident, on-chain-settleable audit trail for every host-call a governed AI agent makes during its execution lifetime. For each crossing of the Wasm/host boundary—whether an LLM inference call, a filesystem write, a web fetch, or any other capability dispatch—the Loom host captures the call's inputs, outputs, a monotonically-incrementing sequence number, the governing Kernel Warrant identifier, and wall-clock epoch time. These fields are SHA-256-hashed into a compact **HostCallReceipt**. All receipts produced in a single governed execution session are accumulated into a binary **PoGE Merkle Tree**. The resulting 32-byte Merkle root, together with the Warrant ID and session metadata, is posted to a Solidity smart contract on Base Sepolia, creating an immutable, publicly-verifiable record of every action the AI agent took—and nothing it did not. The protocol is designed to add no more than ~4 µs of latency per host-call and to hold a constant ≤ 2 MiB of in-process memory for a trace of up to 65,535 receipts regardless of payload size, using streaming SHA-256 and a pre-allocated receipt ring buffer.

---

## Table of Contents

1. [Motivation and Threat Model](#1-motivation-and-threat-model)
2. [Terminology](#2-terminology)
3. [Protocol Overview](#3-protocol-overview)
4. [Data Structures](#4-data-structures)
   - 4.1 [KernelWarrant](#41-kernelwarrant)
   - 4.2 [HostCallKind](#42-hostcallkind)
   - 4.3 [HostCallEvent](#43-hostcallevent)
   - 4.4 [HostCallReceipt](#44-hostcallreceipt)
   - 4.5 [PoGETrace](#45-pogetrace)
   - 4.6 [PoGEMerkleTree](#46-pogenerkletree)
   - 4.7 [PoGEAuditRoot](#47-pogeauditroot)
   - 4.8 [PoGEInterceptor](#48-pogeinterceptor)
5. [Cryptographic Hashing Flow](#5-cryptographic-hashing-flow)
   - 5.1 [Domain Separation](#51-domain-separation)
   - 5.2 [HostCallReceipt Digest Construction](#52-hostcallreceipt-digest-construction)
   - 5.3 [Merkle Tree Construction](#53-merkle-tree-construction)
   - 5.4 [Audit Root Finalization](#54-audit-root-finalization)
6. [Rust Implementation Strategy](#6-rust-implementation-strategy)
   - 6.1 [Intercepting the Wasmtime Linker Boundary](#61-intercepting-the-wasmtime-linker-boundary)
   - 6.2 [Streaming Hash to Prevent Memory Bloat](#62-streaming-hash-to-prevent-memory-bloat)
   - 6.3 [Pre-Allocated Ring Buffer for Receipt Accumulation](#63-pre-allocated-ring-buffer-for-receipt-accumulation)
   - 6.4 [Thread Safety and Concurrency Model](#64-thread-safety-and-concurrency-model)
   - 6.5 [Fuel Metering Integration](#65-fuel-metering-integration)
7. [EVM Settlement Layer](#7-evm-settlement-layer)
   - 7.1 [MeridianAuditLog Contract Interface](#71-meridianauditlog-contract-interface)
   - 7.2 [Calldata Encoding](#72-calldata-encoding)
   - 7.3 [Verification Query Pattern](#73-verification-query-pattern)
8. [Security Analysis](#8-security-analysis)
   - 8.1 [Collision Resistance](#81-collision-resistance)
   - 8.2 [Warrant Binding and Replay Protection](#82-warrant-binding-and-replay-protection)
   - 8.3 [Host Integrity Assumption](#83-host-integrity-assumption)
   - 8.4 [Omission Attacks](#84-omission-attacks)
9. [Memory and Performance Budget](#9-memory-and-performance-budget)
10. [Implementation Phases and Acceptance Criteria](#10-implementation-phases-and-acceptance-criteria)
11. [Open Questions and Future Extensions](#11-open-questions-and-future-extensions)
12. [References](#12-references)

---

## 1. Motivation and Threat Model

### 1.1 The Verifiable Digital Labor Problem

Enterprise SecOps and regulatory frameworks (SOC 2 Type II, ISO 27001, NIST AI RMF) increasingly require that autonomous AI agents produce a _continuous, tamper-evident record_ of every action they take. The Meridian Loom runtime executes untrusted Wasm AI agents under strict governance from the Kernel—but until now the host-call boundary has been a trust gap: the Kernel can authorize or deny capability dispatch, yet there is no cryptographic proof that a given authorized call _actually fired_, what its inputs were, what it returned, or in which sequence. An adversary controlling the guest Wasm module or a compromised orchestration layer could:

- **Replay** a prior authorized call with different arguments after the fact.
- **Inject** synthetic call records into an audit log stored in mutable storage.
- **Suppress** calls from an audit log selectively to hide exfiltration.
- **Dispute** the outputs returned by a third-party LLM to deny liability.

The PoGE protocol closes this gap by binding each host-call event cryptographically to its Kernel Warrant, producing receipts that are non-repudiable and independently verifiable by any party with access to the EVM chain.

### 1.2 Actors

| Actor | Trust Level | Role |
|---|---|---|
| **Kernel** | Fully trusted | Issues `KernelWarrant`; signs session metadata |
| **Loom Host** | Trusted | Executes Wasm; runs the `PoGEInterceptor`; posts audit roots |
| **Guest (Wasm Module)** | Untrusted | AI agent logic; cannot influence receipt contents |
| **External Services** | Untrusted | LLM APIs, web origins, FS—their responses are hashed verbatim |
| **Verifier** | Third party | Reads Merkle root from chain; reconstructs and verifies receipts |

### 1.3 Threat Model Boundaries

PoGE provides **integrity** of the execution trace within a single governed session: it does not provide confidentiality (receipt inputs/outputs should be treated as sensitive and may require encryption at rest), liveness (the host may still crash), or Byzantine fault tolerance. The threat model assumes the Loom host process itself is not compromised. TEE-based host attestation is a planned future extension (see §11).

---

## 2. Terminology

| Term | Definition |
|---|---|
| **Warrant** | A signed, time-bounded authorization token issued by the Kernel, scoping which capabilities the guest may invoke. Each warrant carries a globally unique 32-byte ID. |
| **Host-Call** | Any invocation of a capability crossing the Wasm/host boundary: LLM inference, filesystem I/O, network fetch, clock read, RNG sample, etc. |
| **Receipt** | A 32-byte SHA-256 digest binding one host-call's inputs, outputs, sequence number, and warrant ID. The smallest unit of evidence in the PoGE protocol. |
| **Trace** | The ordered sequence of all receipts produced during a single governed execution session. |
| **Merkle Root** | The 32-byte root of the binary PoGE Merkle Tree constructed over the trace. |
| **Audit Root** | The Merkle Root plus session metadata posted on-chain. |
| **Settlement** | The act of calling `MeridianAuditLog.settle()` on the EVM contract to record an Audit Root permanently. |
| **Domain Tag** | A fixed ASCII prefix prepended before data fed into a SHA-256 hasher to provide domain separation and prevent cross-protocol hash collisions. |

---

## 3. Protocol Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│  KERNEL                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │  KernelWarrant { id: [u8;32], scope, expiry, kernel_sig }    │          │
│  └───────────────────────────────┬──────────────────────────────┘          │
│                                  │ issue                                   │
└──────────────────────────────────┼─────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────────┐
│  LOOM HOST (Trusted)                                                        │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  PoGEInterceptor                                                     │  │
│  │  ┌──────────┐  HostCallEvent   ┌────────────────┐  Receipt (32B)    │  │
│  │  │ Linker   ├─────────────────►│ receipt_for()  ├──────────────────►│  │
│  │  │ func_wrap│  (kind, args,    │ SHA-256 stream │  PoGETrace         │  │
│  │  │ shim     │   result, seq,   │ domain-sep     │  (ring buffer)     │  │
│  │  │          │   warrant_id,    └────────────────┘                    │  │
│  │  │          │   epoch_ms)                                             │  │
│  │  └──────────┘                                                         │  │
│  │                                                                       │  │
│  │  ┌───────────────────────────────────────────────────────────────┐   │  │
│  │  │  finalize()                                                   │   │  │
│  │  │  PoGEMerkleTree::build(trace) ──► Merkle Root [u8;32]        │   │  │
│  │  │  PoGEAuditRoot { root, warrant_id, trace_len, epoch_range }  │   │  │
│  │  └───────────────────────────┬───────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                 │ settle()                                  │
└─────────────────────────────────┼───────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼───────────────────────────────────────────┐
│  BASE SEPOLIA (EVM)                                                          │
│  MeridianAuditLog contract                                                  │
│  event AuditRootSettled(root, warrantId, traceLen, epochStart, epochEnd)    │
└─────────────────────────────────────────────────────────────────────────────┘
```

The protocol executes in three phases:

1. **Interception Phase** — Each host-call fires a shim registered via Wasmtime's `Linker::func_wrap`. The shim captures call kind, canonical input bytes, canonical output bytes, the current sequence counter, and the Warrant ID, then invokes `PoGEInterceptor::record_event()`.

2. **Accumulation Phase** — `record_event()` constructs a `HostCallEvent`, computes its SHA-256 receipt via a streaming hasher (no full payload buffering), and appends the 32-byte receipt to the `PoGETrace` ring buffer.

3. **Settlement Phase** — At execution end (or on demand for long-running sessions), `PoGEInterceptor::finalize()` builds the `PoGEMerkleTree` from the trace, extracts the root, packages a `PoGEAuditRoot`, and submits it to the `MeridianAuditLog` smart contract on Base Sepolia via an EIP-1559 transaction.

---

## 4. Data Structures

All structures below are new Rust types introduced in a new crate `loom-poge`. They do not modify any existing `.rs` file. They integrate with existing types (`WasmExecutionRequest`, `WasmHostConfig`) by reference.

### 4.1 KernelWarrant

```rust
/// A governance credential issued by the Meridian Kernel before execution
/// begins. The `id` field is the canonical 32-byte warrant identifier that
/// flows into every HostCallReceipt produced during the session it governs.
///
/// # Security Note
/// `KernelWarrant` is issued out-of-band by the Kernel and passed into the
/// Loom host at session start. It MUST be verified (signature check over
/// `id || scope_hash || expiry_epoch_ms`) before being accepted by the
/// PoGEInterceptor. The signature verification algorithm is Ed25519 using
/// the Kernel's published long-term key.
#[derive(Clone, Debug)]
pub struct KernelWarrant {
    /// Globally unique 32-byte identifier. Used as a binding tag in every
    /// HostCallReceipt produced under this warrant.
    pub id: [u8; 32],

    /// CBOR-encoded scope descriptor: which capability kinds are authorized,
    /// per-kind rate limits, and any content-policy selectors.
    pub scope_cbor: Vec<u8>,

    /// UTC milliseconds at which this warrant expires. The PoGEInterceptor
    /// MUST reject host-calls attempted after this timestamp.
    pub expiry_epoch_ms: u64,

    /// Ed25519 signature by the Kernel over SHA-256(id || scope_cbor || expiry_epoch_ms_be).
    pub kernel_sig: [u8; 64],

    /// Public key that produced kernel_sig. Callers validate this against the
    /// Kernel's pinned trust anchor before use.
    pub kernel_pub: [u8; 32],
}
```

### 4.2 HostCallKind

```rust
/// Enumerates every category of Wasm/host boundary crossing that the Loom
/// runtime exposes to guest agents. Each variant maps one-to-one to a
/// Wasmtime-linked host function namespace.
///
/// The numeric discriminant is serialized into receipt digests; values are
/// therefore STABLE and MUST NOT be reordered. New variants are appended.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum HostCallKind {
    /// LLM inference call (prompt in, completion out).
    LlmInference    = 0x01,
    /// Filesystem read: path → bytes.
    FsRead          = 0x02,
    /// Filesystem write: path + bytes → ack.
    FsWrite         = 0x03,
    /// HTTP/HTTPS fetch: request → response.
    WebFetch        = 0x04,
    /// High-resolution wall clock read: () → epoch_ms.
    ClockNow        = 0x05,
    /// Cryptographically secure random bytes: len → bytes.
    RngBytes        = 0x06,
    /// Structured key-value store get: key → value.
    KvGet           = 0x07,
    /// Structured key-value store put: key + value → ack.
    KvPut           = 0x08,
    /// Sub-agent spawn: descriptor → agent_id.
    AgentSpawn      = 0x09,
    /// Sub-agent join/result retrieval: agent_id → result_bytes.
    AgentJoin       = 0x0A,
    /// Log emission: level + message → ack.
    LogEmit         = 0x0B,
    /// Metric emission: name + value → ack.
    MetricEmit      = 0x0C,
    /// Catch-all for extension host functions not yet enumerated.
    Extension       = 0xFF,
}

impl HostCallKind {
    /// Returns the 1-byte discriminant used in domain-separated hashing.
    #[inline(always)]
    pub fn as_byte(self) -> u8 {
        self as u8
    }
}
```

### 4.3 HostCallEvent

```rust
/// The raw, pre-digest record of a single host-call crossing. Produced
/// synchronously inside the Wasmtime shim before control returns to the guest.
///
/// # Memory Policy
/// `input_bytes` and `output_bytes` are passed as slices (`&[u8]`) to the
/// receipt constructor and are NEVER stored in this struct after the receipt
/// digest has been computed. This ensures O(1) memory overhead per event
/// regardless of payload size. The fields below are all ≤ 64 bytes.
#[derive(Clone, Debug)]
pub struct HostCallEvent<'a> {
    /// Category of host-call.
    pub kind: HostCallKind,

    /// Monotonically increasing counter within this governed session.
    /// Starts at 0. Overflow at u32::MAX causes the session to be
    /// terminated with a TraceOverflow error.
    pub sequence: u32,

    /// 32-byte governing Warrant ID copied from the session's KernelWarrant.
    pub warrant_id: [u8; 32],

    /// UTC milliseconds at the moment the host-call was dispatched (pre-call).
    pub dispatch_epoch_ms: u64,

    /// Canonical byte representation of the call's input arguments.
    /// For complex inputs (structs, JSON), this is the deterministic
    /// CBOR serialization. For raw byte blobs, this is the blob itself.
    /// Passed by reference; never heap-allocated inside HostCallEvent.
    pub input_bytes: &'a [u8],

    /// Canonical byte representation of the call's output/return value.
    /// Same serialization convention as input_bytes.
    pub output_bytes: &'a [u8],

    /// True if the host-call resulted in an error. Error detail is
    /// encoded in output_bytes as a UTF-8 string.
    pub is_error: bool,
}
```

### 4.4 HostCallReceipt

```rust
/// A 32-byte SHA-256 digest representing one verified host-call event.
/// This is the smallest unit of evidence in the PoGE protocol.
///
/// The receipt is computed by `PoGEInterceptor::receipt_for()` and stored
/// in the `PoGETrace`. It is NOT possible to reconstruct the original
/// input/output payloads from a receipt alone; the receipt is a commitment.
///
/// Receipts are deterministic: identical `HostCallEvent` fields always
/// produce the same receipt. This allows independent re-computation
/// by any verifier who holds the original call log.
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
        self.0.iter().map(|b| format!("{:02x}", b)).collect()
    }
}
```

### 4.5 PoGETrace

```rust
/// An ordered, bounded collection of HostCallReceipts produced during a
/// single governed execution session.
///
/// # Capacity and Memory Budget
/// The ring buffer is pre-allocated at session start with capacity
/// `MAX_TRACE_RECEIPTS`. Each receipt occupies exactly 32 bytes, so
/// the maximum memory consumed by the trace itself is:
///
///   65_535 * 32 = 2_097_120 bytes ≈ 2 MiB
///
/// Sessions requiring more than MAX_TRACE_RECEIPTS host-calls MUST be
/// split into checkpointed sub-sessions (see §11.1).
pub const MAX_TRACE_RECEIPTS: usize = 65_535; // u16::MAX

pub struct PoGETrace {
    /// Pre-allocated fixed-capacity buffer of receipts.
    /// Using a Vec with a pre-allocated capacity rather than a heap-ring
    /// because Merkle tree construction requires random access by index.
    receipts: Vec<HostCallReceipt>,

    /// Epoch ms of the first recorded receipt. Set on first push.
    pub epoch_start_ms: Option<u64>,

    /// Epoch ms of the most recently recorded receipt.
    pub epoch_end_ms: Option<u64>,
}

impl PoGETrace {
    /// Allocate the trace buffer, reserving the full memory budget upfront
    /// to prevent reallocation during hot-path recording.
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

    pub fn len(&self) -> usize {
        self.receipts.len()
    }

    pub fn is_empty(&self) -> bool {
        self.receipts.is_empty()
    }

    /// Read-only slice for Merkle tree construction.
    pub fn as_slice(&self) -> &[HostCallReceipt] {
        &self.receipts
    }
}
```

### 4.6 PoGEMerkleTree

```rust
/// A complete binary Merkle tree whose leaves are HostCallReceipts.
///
/// # Construction Algorithm
/// 1. Leaves are the SHA-256 of (`LEAF_TAG || receipt_bytes`).
/// 2. If the leaf count is odd, the last leaf is duplicated (standard
///    Bitcoin/Ethereum convention, for EVM Merkle verifier compatibility).
/// 3. Internal nodes: SHA-256(`BRANCH_TAG || left_child || right_child`).
/// 4. The root is the single node at level 0.
///
/// # Storage
/// The tree is stored as a flat `Vec<[u8; 32]>` in breadth-first order.
/// Level k occupies indices [2^k - 1 .. 2^(k+1) - 1]. The root is at
/// index 0. Total allocation for N leaves:
///
///   ceil(N / 1) leaf nodes + (N - 1) internal nodes = 2N - 1 nodes (padded)
///   Upper bound for N = 65_535: ~131_070 * 32 ≈ 4.2 MiB peak during build.
///   After root extraction the tree allocation is freed (see `finalize()`).
pub struct PoGEMerkleTree {
    /// Flat breadth-first node array. Index 0 is the root.
    nodes: Vec<[u8; 32]>,
    /// Number of leaf nodes (= receipts, padded to next power of 2).
    pub leaf_count: usize,
}

/// Domain tag prepended before hashing leaf nodes.
pub const MERKLE_LEAF_TAG: &[u8] = b"POGE_MERKLE_LEAF_v1\x00";

/// Domain tag prepended before hashing internal branch nodes.
pub const MERKLE_BRANCH_TAG: &[u8] = b"POGE_MERKLE_BRANCH_v1\x00";

impl PoGEMerkleTree {
    /// Build a Merkle tree from an ordered receipt slice.
    ///
    /// Panics if `receipts` is empty; callers must guard against empty traces.
    pub fn build(receipts: &[HostCallReceipt]) -> Self {
        assert!(!receipts.is_empty(), "cannot build Merkle tree from empty trace");

        // Pad leaf count to next power of 2 for a complete binary tree.
        let padded = receipts.len().next_power_of_two();
        let total_nodes = 2 * padded; // Complete binary tree node count.
        let mut nodes: Vec<[u8; 32]> = vec![[0u8; 32]; total_nodes];

        // Hash leaves into the bottom half of the flat array (indices padded..2*padded-1).
        for (i, receipt) in receipts.iter().enumerate() {
            nodes[padded + i] = Self::hash_leaf(receipt);
        }
        // Duplicate last leaf for odd-count padding.
        for i in receipts.len()..padded {
            nodes[padded + i] = nodes[padded + receipts.len() - 1];
        }
        // Build internal nodes bottom-up.
        for i in (1..padded).rev() {
            let left  = nodes[2 * i];
            let right = nodes[2 * i + 1];
            nodes[i] = Self::hash_branch(&left, &right);
        }
        // Node at index 0 is unused (1-indexed tree). Root is at index 1.
        Self { nodes, leaf_count: padded }
    }

    /// Returns the 32-byte Merkle root.
    #[inline(always)]
    pub fn root(&self) -> [u8; 32] {
        self.nodes[1]
    }

    /// Compute a domain-separated leaf hash.
    fn hash_leaf(receipt: &HostCallReceipt) -> [u8; 32] {
        use sha2::{Sha256, Digest};
        let mut h = Sha256::new();
        h.update(MERKLE_LEAF_TAG);
        h.update(receipt.as_bytes());
        h.finalize().into()
    }

    /// Compute a domain-separated branch hash.
    fn hash_branch(left: &[u8; 32], right: &[u8; 32]) -> [u8; 32] {
        use sha2::{Sha256, Digest};
        let mut h = Sha256::new();
        h.update(MERKLE_BRANCH_TAG);
        h.update(left);
        h.update(right);
        h.finalize().into()
    }

    /// Generate a Merkle inclusion proof for the receipt at `index`.
    ///
    /// Returns an ordered list of sibling hashes from leaf to root,
    /// compatible with OpenZeppelin's `MerkleProof.verify()` convention.
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
```

### 4.7 PoGEAuditRoot

```rust
/// The finalized, on-chain-settleable record for one governed execution session.
///
/// This struct is ABI-encoded (via `ethabi` or equivalent) before being
/// passed as `calldata` to `MeridianAuditLog.settle()`.
#[derive(Clone, Debug)]
pub struct PoGEAuditRoot {
    /// 32-byte Merkle root of the full execution trace.
    pub merkle_root: [u8; 32],

    /// 32-byte Kernel Warrant ID that governed this session.
    pub warrant_id: [u8; 32],

    /// Total number of host-call receipts in the trace (before Merkle padding).
    pub trace_len: u32,

    /// UTC milliseconds of the first recorded host-call in this session.
    pub epoch_start_ms: u64,

    /// UTC milliseconds of the last recorded host-call in this session.
    pub epoch_end_ms: u64,

    /// SHA-256 of the `WasmGuestSource::WasmBytes` payload, identifying which
    /// compiled module was executing. Provides module-level non-repudiation.
    pub module_digest: [u8; 32],

    /// Human-readable session label for off-chain indexing (max 64 bytes,
    /// truncated on-chain in the event's `label` topic).
    pub session_label: String,
}
```

### 4.8 PoGEInterceptor

```rust
/// The central mutable object that lives for the duration of one governed
/// execution session. Shared between the Wasmtime `Linker` shim closures
/// and the session lifecycle manager via `Arc<Mutex<PoGEInterceptor>>`.
///
/// # Lifecycle
/// 1. Instantiate with `PoGEInterceptor::new(warrant, module_digest, label)`.
/// 2. Register shims: pass a reference to `Linker::func_wrap` closures.
/// 3. Run the guest Wasm module.
/// 4. Call `finalize()` to obtain the `PoGEAuditRoot`.
/// 5. Submit the audit root to the EVM settlement layer.
pub struct PoGEInterceptor {
    warrant: KernelWarrant,
    module_digest: [u8; 32],
    session_label: String,
    trace: PoGETrace,
    sequence: u32,
}

impl PoGEInterceptor {
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

    /// Compute the receipt for a host-call event and push it to the trace.
    ///
    /// This is the hot-path entry point called from every Wasmtime shim.
    /// It MUST complete in constant time relative to payload size; the
    /// streaming hasher in `receipt_for()` ensures this.
    pub fn record_event(
        &mut self,
        kind: HostCallKind,
        dispatch_epoch_ms: u64,
        input_bytes: &[u8],
        output_bytes: &[u8],
        is_error: bool,
    ) -> Result<HostCallReceipt, PoGEError> {
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
        self.sequence = self.sequence.checked_add(1).ok_or(PoGEError::TraceOverflow)?;
        Ok(receipt)
    }

    /// Finalize the session: build the Merkle tree, return the PoGEAuditRoot.
    ///
    /// Consumes the interceptor. The Merkle tree allocation is freed after
    /// root extraction.
    pub fn finalize(self) -> Result<PoGEAuditRoot, PoGEError> {
        if self.trace.is_empty() {
            return Err(PoGEError::EmptyTrace);
        }
        let tree = PoGEMerkleTree::build(self.trace.as_slice());
        let root = tree.root();
        // tree is dropped here; its ~4 MiB allocation is freed.
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

    /// Compute the 32-byte SHA-256 receipt for a single HostCallEvent.
    ///
    /// The streaming hasher processes fields sequentially without building
    /// a single concatenated buffer; peak memory is one SHA-256 context
    /// (≈ 256 bytes) plus the hasher's internal 64-byte block.
    fn receipt_for(event: &HostCallEvent<'_>) -> HostCallReceipt {
        use sha2::{Sha256, Digest};
        let mut h = Sha256::new();
        // --- Domain Tag ---
        h.update(b"POGE_RECEIPT_v1\x00");
        // --- Kind discriminant (1 byte) ---
        h.update(&[event.kind.as_byte()]);
        // --- Sequence number (4 bytes, big-endian) ---
        h.update(&event.sequence.to_be_bytes());
        // --- Warrant ID (32 bytes) ---
        h.update(&event.warrant_id);
        // --- Dispatch epoch ms (8 bytes, big-endian) ---
        h.update(&event.dispatch_epoch_ms.to_be_bytes());
        // --- Input length (4 bytes, big-endian) for length-prefix framing ---
        h.update(&(event.input_bytes.len() as u32).to_be_bytes());
        // --- Input bytes (variable) ---
        h.update(event.input_bytes);
        // --- Output length (4 bytes, big-endian) ---
        h.update(&(event.output_bytes.len() as u32).to_be_bytes());
        // --- Output bytes (variable) ---
        h.update(event.output_bytes);
        // --- Error flag (1 byte) ---
        h.update(&[event.is_error as u8]);
        HostCallReceipt(h.finalize().into())
    }
}

/// Errors produced by the PoGE system.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PoGEError {
    /// Trace has reached MAX_TRACE_RECEIPTS and cannot accept more events.
    TraceOverflow,
    /// Session was finalized with no recorded host-calls.
    EmptyTrace,
    /// The KernelWarrant's expiry has passed at the time of a host-call.
    WarrantExpired,
    /// Ed25519 signature on the KernelWarrant is invalid.
    WarrantSignatureInvalid,
    /// EVM settlement transaction failed.
    SettlementFailed(String),
}
```

---

## 5. Cryptographic Hashing Flow

### 5.1 Domain Separation

All SHA-256 invocations in the PoGE protocol are domain-separated by a fixed ASCII tag terminated with a null byte (`\x00`). This prevents cross-context hash collisions where an attacker might craft a receipt-shaped Merkle leaf or a leaf-shaped receipt:

| Context | Tag |
|---|---|
| Receipt (host-call event) | `POGE_RECEIPT_v1\x00` |
| Merkle leaf node | `POGE_MERKLE_LEAF_v1\x00` |
| Merkle branch node | `POGE_MERKLE_BRANCH_v1\x00` |
| Audit root finalization | `POGE_AUDIT_ROOT_v1\x00` |

The null byte terminator ensures tags of different lengths cannot produce the same prefix by coincidence.

### 5.2 HostCallReceipt Digest Construction

For an event with fields `(kind, seq, warrant_id, epoch_ms, input, output, is_error)`:

```
receipt = SHA-256(
    "POGE_RECEIPT_v1\x00"      -- 16 bytes, domain tag
    || kind_byte               -- 1 byte,  HostCallKind discriminant
    || seq_be                  -- 4 bytes, big-endian u32
    || warrant_id              -- 32 bytes
    || epoch_ms_be             -- 8 bytes, big-endian u64
    || len(input)_be           -- 4 bytes, big-endian u32, length prefix
    || input                   -- variable
    || len(output)_be          -- 4 bytes, big-endian u32, length prefix
    || output                  -- variable
    || is_error_byte           -- 1 byte, 0x00 or 0x01
)
```

**Length-prefix framing** (`len(input)_be || input`) is essential: without it, the concatenation `"ab" || "cd"` is indistinguishable from `"a" || "bcd"`, enabling collision construction. All variable-length fields in PoGE receipts are length-prefixed.

**Endianness convention**: All multi-byte integers are serialized big-endian (network byte order), consistent with EVM ABI encoding and maximizing compatibility with EVM-native Merkle verifiers.

### 5.3 Merkle Tree Construction

Given N receipts `R_0, R_1, ..., R_{N-1}`:

**Step 1 — Leaf hashing:**
```
L_i = SHA-256("POGE_MERKLE_LEAF_v1\x00" || R_i)   for i in 0..N
```

**Step 2 — Padding to power-of-2:**
```
P = next_power_of_2(N)
L_i = L_{N-1}   for i in N..P     (last leaf duplication)
```

**Step 3 — Bottom-up internal node construction:**
```
B_{k, j} = SHA-256("POGE_MERKLE_BRANCH_v1\x00" || B_{k+1, 2j} || B_{k+1, 2j+1})
```
where level `k+1` are the children of level `k`, and level `log2(P)` contains the leaves.

**Step 4 — Root:**
```
Merkle Root = B_{0, 0}    (the single node at the top)
```

This construction is compatible with OpenZeppelin `MerkleProof.verify()` when proofs are generated with `PoGEMerkleTree::proof_for()`, enabling EVM-native inclusion proofs without a bespoke verifier contract.

### 5.4 Audit Root Finalization

The `PoGEAuditRoot` struct is ABI-encoded into calldata for on-chain settlement. The fields are packed into a `bytes32`-aligned layout:

```
ABI_ENCODED_AUDIT_ROOT = abi.encode(
    merkle_root      : bytes32,
    warrant_id       : bytes32,
    module_digest    : bytes32,
    trace_len        : uint32,
    epoch_start_ms   : uint64,
    epoch_end_ms     : uint64,
    session_label    : string
)
```

---

## 6. Rust Implementation Strategy

### 6.1 Intercepting the Wasmtime Linker Boundary

The Loom host exposes capabilities to the guest via Wasmtime's `Linker::func_wrap` mechanism. Currently these shims live in `capability_shims.rs` and dispatch to `capabilities.rs`. The PoGE layer intercepts **after** the capability call returns but **before** the result is transferred back to the Wasm linear memory.

The integration pattern uses a shared `Arc<Mutex<PoGEInterceptor>>` passed into each `func_wrap` closure at linker-build time:

```rust
// In loom-poge/src/linker.rs (NEW FILE — does not modify capability_shims.rs)

use std::sync::{Arc, Mutex};
use wasmtime::Linker;
use crate::{HostCallKind, PoGEInterceptor};

/// Wraps an existing Linker with PoGE interception.
///
/// For each host function already registered in `base_linker`, this function
/// re-registers a shim that: (1) forwards the call to the original handler,
/// (2) captures inputs and outputs, (3) records a receipt via the interceptor.
///
/// This approach is additive: it does not modify any existing source file.
pub fn with_poge_interception<T>(
    base_linker: Linker<T>,
    interceptor: Arc<Mutex<PoGEInterceptor>>,
) -> Linker<T>
where
    T: Send + 'static,
{
    // Implementation composes the existing linker with interception closures.
    // Each closure captures `Arc::clone(&interceptor)` — cheap reference-count
    // bump, no data copy.
    todo!("wire per-capability shim closures here")
}
```

**Why `Arc<Mutex<PoGEInterceptor>>` and not a per-thread interceptor?**

Wasmtime's `func_wrap` closures are `Fn + Send + Sync`. The interceptor must be shared across potentially multiple async tasks that may service different host-call kinds concurrently (e.g., a parallel LLM call and a background FS read). `Mutex` provides the necessary serialization; because receipts must be ordered by `sequence`, the `record_event()` critical section is short (one streaming SHA-256 update + one `Vec::push`) and contention is negligible.

**Alternative: lock-free MPSC channel approach.** For deployments requiring sub-microsecond interception latency, each `func_wrap` shim pushes a raw `HostCallEvent` (with owned `input_bytes`/`output_bytes` clones) onto a `std::sync::mpsc::SyncSender`. A dedicated receipt-building thread drains the channel, computes receipts, and appends to the trace. This trades latency for throughput but requires careful shutdown ordering; it is described as an optional upgrade path in §11.

### 6.2 Streaming Hash to Prevent Memory Bloat

The critical design constraint is: **the full input and output byte payloads of host-calls are never simultaneously resident in memory for hashing purposes.** This is achieved by using `sha2::Sha256::update()` in a streaming fashion:

```rust
// Pseudocode for zero-copy streaming hash inside receipt_for()

let mut h = Sha256::new();
h.update(DOMAIN_TAG);
h.update(&[kind_byte, ...]);          // fixed fields, on stack
h.update(&len(input).to_be_bytes());  // length prefix
h.update(input_bytes);               // SLICE REFERENCE — no copy
h.update(&len(output).to_be_bytes()); // length prefix
h.update(output_bytes);              // SLICE REFERENCE — no copy
let digest: [u8; 32] = h.finalize().into();
```

`sha2::Sha256::update()` internally processes data in 64-byte blocks, buffering only a single block (64 bytes) plus the running state (32 bytes). For a 1 MiB LLM response, the peak allocator pressure from the hasher is 96 bytes — a 10,000× improvement over a naive concatenate-then-hash approach.

### 6.3 Pre-Allocated Ring Buffer for Receipt Accumulation

`PoGETrace::new()` calls `Vec::with_capacity(MAX_TRACE_RECEIPTS)` at session initialization, reserving the full 2 MiB upfront. This has two effects:

1. **No reallocation during the hot path.** `Vec::push` into a pre-allocated `Vec` is an `O(1)` operation with no allocator interaction until capacity is reached.
2. **Predictable RSS footprint.** The Loom host can account for the 2 MiB reservation in its memory budget calculations (`WasmStoreLimits::max_memory_bytes`) and apply back-pressure before launching a new session if headroom is insufficient.

For sessions that are known to be short (e.g., ≤ 256 receipts), `PoGETrace::with_capacity(n)` is provided as an optimization constructor.

### 6.4 Thread Safety and Concurrency Model

```
Session lifetime:
  Main thread:        PoGEInterceptor::new() → register shims → run guest
  Wasmtime threads:   func_wrap closures → Mutex<PoGEInterceptor>::lock() → record_event()
  Shutdown:           main thread acquires lock → finalize() → submit to EVM
```

The `PoGEInterceptor` does not implement `Clone`. The `Arc<Mutex<>>` wrapper is the canonical sharing primitive. `finalize()` takes `self` (consuming), guaranteeing that once finalization begins no further `record_event()` calls can succeed.

### 6.5 Fuel Metering Integration

The Loom runtime already employs Wasmtime fuel metering (`WasmHostConfig::fuel_metering_enabled`). PoGE adds a complementary constraint: the sequence counter `u32::MAX` (4,294,967,295) is an absolute upper bound on host-calls, but `MAX_TRACE_RECEIPTS` (65,535) is the tighter operational limit. Session fuel budgets should be calibrated so that a guest cannot exhaust fuel through host-calls alone without triggering a `TraceOverflow` first, ensuring the trace is always structurally complete when finalize is called.

Recommended fuel-to-hostcall ratio: allocate at least **1,000 fuel units per expected host-call** to prevent fuel exhaustion from masking a trace overflow.

---

## 7. EVM Settlement Layer

### 7.1 MeridianAuditLog Contract Interface

The following Solidity interface is the **canonical specification**; the implementation is deployed independently of this document.

```solidity
// SPDX-License-Identifier: MIT
// Target: Base Sepolia (Chain ID: 84532)
// Compiler: solc 0.8.24

interface IMeridianAuditLog {

    /// @notice Emitted once per settled execution session.
    /// @param merkleRoot   32-byte PoGE Merkle root of the execution trace.
    /// @param warrantId    32-byte Kernel Warrant ID that governed the session.
    /// @param moduleDigest SHA-256 of the executed Wasm module bytes.
    /// @param traceLen     Number of host-call receipts in the trace.
    /// @param epochStart   UTC milliseconds of the first host-call.
    /// @param epochEnd     UTC milliseconds of the last host-call.
    /// @param settler      Address that submitted this settlement.
    event AuditRootSettled(
        bytes32 indexed merkleRoot,
        bytes32 indexed warrantId,
        bytes32         moduleDigest,
        uint32          traceLen,
        uint64          epochStart,
        uint64          epochEnd,
        address indexed settler
    );

    /// @notice Settle one governed execution session on-chain.
    ///
    /// The function is intentionally non-restrictive on the caller: any
    /// address may settle any audit root. Authorization is enforced off-chain
    /// by requiring a valid KernelWarrant signature that corresponds to the
    /// warrantId. Duplicate settlements of the same merkleRoot + warrantId
    /// are silently accepted (idempotent), enabling retry on RPC failure.
    ///
    /// @param merkleRoot   PoGE Merkle root (see §5.3).
    /// @param warrantId    Kernel Warrant ID from the governing KernelWarrant.
    /// @param moduleDigest SHA-256 of the Wasm module bytes.
    /// @param traceLen     Total host-call count (uint32 to fit in one slot).
    /// @param epochStart   Epoch ms of first receipt.
    /// @param epochEnd     Epoch ms of last receipt.
    /// @param sessionLabel UTF-8 human label (max 64 bytes; truncated if longer).
    function settle(
        bytes32 merkleRoot,
        bytes32 warrantId,
        bytes32 moduleDigest,
        uint32  traceLen,
        uint64  epochStart,
        uint64  epochEnd,
        string  calldata sessionLabel
    ) external;

    /// @notice Returns true if a given (merkleRoot, warrantId) pair has been
    ///         previously settled. Enables instant verifier queries without
    ///         scanning event logs.
    function isSettled(
        bytes32 merkleRoot,
        bytes32 warrantId
    ) external view returns (bool);

    /// @notice Returns the block number at which the given pair was settled,
    ///         or 0 if not settled.
    function settledAtBlock(
        bytes32 merkleRoot,
        bytes32 warrantId
    ) external view returns (uint256);
}
```

### 7.2 Calldata Encoding

The Rust settlement client (in `loom-poge/src/evm_settler.rs`) encodes the `PoGEAuditRoot` into calldata using standard ABI encoding:

```rust
/// Encode a PoGEAuditRoot as calldata for IMeridianAuditLog.settle().
///
/// Uses the `ethabi` crate for ABI encoding; no external JSON ABI file needed.
pub fn encode_settle_calldata(root: &PoGEAuditRoot) -> Vec<u8> {
    use ethabi::{Function, Param, ParamType, Token, encode};

    // Function selector: keccak256("settle(bytes32,bytes32,bytes32,uint32,uint64,uint64,string)")[0..4]
    // Pre-computed: 0xa1b2c3d4  (replace with actual selector at deployment)
    let selector: [u8; 4] = SETTLE_SELECTOR;

    let tokens = vec![
        Token::FixedBytes(root.merkle_root.to_vec()),
        Token::FixedBytes(root.warrant_id.to_vec()),
        Token::FixedBytes(root.module_digest.to_vec()),
        Token::Uint(root.trace_len.into()),
        Token::Uint(root.epoch_start_ms.into()),
        Token::Uint(root.epoch_end_ms.into()),
        Token::String(root.session_label.clone()),
    ];

    let mut calldata = selector.to_vec();
    calldata.extend_from_slice(&encode(&tokens));
    calldata
}
```

### 7.3 Verification Query Pattern

A third-party verifier can independently verify a governed execution session using only:

1. The `AuditRootSettled` event from Base Sepolia (queryable via any EVM RPC).
2. The original host-call log (inputs, outputs, timestamps, kinds) provided by the session operator.
3. The Kernel's public key (pinned in the verifier's trust store).

**Verification algorithm:**

```
1. Fetch event: (merkleRoot, warrantId, traceLen, epochStart, epochEnd) from chain.
2. For each host-call i in 0..traceLen:
   a. Reconstruct HostCallEvent from the operator-provided log.
   b. Compute receipt_i = SHA-256(POGE_RECEIPT_v1\x00 || fields...)
3. Build PoGEMerkleTree from receipt_0..receipt_{traceLen-1}.
4. Assert computed_root == merkleRoot from chain.
5. Verify KernelWarrant.kernel_sig using warrantId and Kernel public key.
6. Assert warrant expiry_epoch_ms >= epochStart.
```

This verification is O(N) in the trace length, requires no trusted third party, and can be implemented in any language with SHA-256 support.

---

## 8. Security Analysis

### 8.1 Collision Resistance

SHA-256 provides 128-bit collision resistance (birthday bound on the 256-bit output space). For a trace of 65,535 receipts, the probability of any two receipts colliding is approximately:

```
P(collision) ≈ (65535)^2 / 2^257 ≈ 4.29e9 / 2.3e77 ≈ 1.9e-68
```

This is negligible under any realistic threat model. Domain separation (§5.1) further ensures that a Merkle leaf cannot be confused with an internal node even if an adversary constructs a receipt whose bytes happen to equal a valid branch hash.

### 8.2 Warrant Binding and Replay Protection

Every receipt embeds the 32-byte `warrant_id` directly into the SHA-256 input stream (§5.2). This means:

- A receipt produced under Warrant A **cannot** be transplanted into a trace governed by Warrant B without invalidating every receipt.
- Replaying the same host-call arguments in a different session produces a different receipt because the `sequence` counter and `dispatch_epoch_ms` also change.
- Even an exact replay at the same epoch (clock drift ≤ 1 ms) produces a different receipt because the sequence counter is monotonically incremented and is unique within each session.

### 8.3 Host Integrity Assumption

PoGE assumes the Loom host process is not compromised. A malicious host could:
- Selectively omit `record_event()` calls for certain host-calls.
- Fabricate receipts by generating synthetic events that never fired.
- Report a different `module_digest` than the actual Wasm bytes.

These attacks are mitigated by:
1. **Module digest binding**: the `module_digest` in `PoGEAuditRoot` commits to which code ran. If the host lies about the module, the Kernel warrant (which may embed a module-hash restriction in `scope_cbor`) will not validate.
2. **TEE hosting** (planned, §11.2): running the Loom host inside an Intel TDX or AMD SEV-SNP enclave produces a remote attestation that cryptographically bounds the host binary.
3. **Threshold settlement**: requiring M-of-N independent Loom replicas to independently produce and settle matching audit roots before the Kernel releases credentials.

### 8.4 Omission Attacks

An adversary who controls the guest Wasm module could attempt to overwhelm the trace buffer (triggering `TraceOverflow`) by issuing `MAX_TRACE_RECEIPTS` no-op host-calls before the sensitive call, burying it in a noise trace. Mitigations:

1. **Per-kind rate limits in KernelWarrant scope**: the warrant's `scope_cbor` specifies the maximum number of calls per `HostCallKind` per session.
2. **Fuel metering**: the Wasmtime fuel budget caps total computational work; each host-call consumes a minimum fuel quantum, making flooding attacks expensive.
3. **TraceOverflow = hard stop**: the session is terminated on `TraceOverflow`; no further calls succeed. The partial trace is still settled, preserving evidence of the flood attempt.

---

## 9. Memory and Performance Budget

| Component | Peak Allocation | Notes |
|---|---|---|
| `PoGETrace` (pre-allocated) | 2.00 MiB | `65_535 × 32 bytes`; reserved at session start |
| `PoGEMerkleTree` (during build) | ≤ 4.19 MiB | `2 × 65_536 × 32 bytes`; freed after `root()` |
| SHA-256 streaming context | 96 bytes | One `sha2::Sha256` struct per call |
| `HostCallEvent` on stack | ≤ 80 bytes | All pointer fields; payloads not owned |
| `PoGEAuditRoot` | ≤ 256 bytes | Fixed-size + session label |
| **Total peak (build phase)** | **≤ 6.24 MiB** | During `finalize()` only |
| **Total steady-state** | **≤ 2.01 MiB** | During execution (trace + context) |

**Latency per host-call:**

| Operation | Estimated Latency |
|---|---|
| `Arc::clone` (shim entry) | ≈ 15 ns |
| `Mutex::lock` (uncontended) | ≈ 25 ns |
| `receipt_for()` for 4 KiB payload | ≈ 2.1 µs (SHA-256 ~1.8 GB/s on modern x86) |
| `Vec::push` to trace | ≈ 5 ns |
| `Mutex::unlock` | ≈ 10 ns |
| **Total overhead per host-call** | **≈ 2.2 µs** |

For a 1 MiB LLM response body, `receipt_for()` takes approximately 555 µs — still negligible relative to the actual inference latency (typically ≥ 500 ms).

---

## 10. Implementation Phases and Acceptance Criteria

### Phase 1 — Core Receipts (Milestone: loom-poge crate ships)

- [ ] New crate `loom-poge` created in workspace with zero modifications to existing `.rs` files.
- [ ] `KernelWarrant`, `HostCallKind`, `HostCallEvent`, `HostCallReceipt`, `PoGETrace`, `PoGEInterceptor` defined and unit-tested.
- [ ] `receipt_for()` produces deterministic output; test vectors published in `loom-poge/tests/receipt_vectors.rs`.
- [ ] Streaming hash confirmed to hold ≤ 96 bytes peak across a 10 MiB payload (tracked via `jemalloc` stats in integration test).
- [ ] `PoGETrace::new()` heap reservation confirmed at exactly `MAX_TRACE_RECEIPTS × 32` bytes.

### Phase 2 — Merkle Accumulator (Milestone: auditable traces)

- [ ] `PoGEMerkleTree::build()` produces roots matching known SHA-256 Merkle vectors.
- [ ] `proof_for()` generates proofs verifiable by a local Solidity `MerkleProof.verify()` call via `revm` in tests.
- [ ] `finalize()` frees tree allocation; `valgrind --tool=massif` confirms no residual allocation after call.
- [ ] Fuzz test: random traces of length 1, 2, 3, 65534, 65535 all produce valid trees.

### Phase 3 — Wasmtime Linker Integration (Milestone: governed execution produces receipts)

- [ ] `with_poge_interception()` wraps existing linker without touching `capability_shims.rs`.
- [ ] Integration test: a synthetic Wasm module performing 10 LLM inference calls + 5 FS writes produces a 15-receipt trace with correct receipt ordering.
- [ ] `sequence` field is strictly monotonic in all captured receipts.
- [ ] `WarrantExpired` error returned when a host-call fires after `warrant.expiry_epoch_ms`.

### Phase 4 — EVM Settlement (Milestone: audit root on Base Sepolia)

- [ ] `MeridianAuditLog` contract deployed to Base Sepolia; address committed to `loom-poge/src/evm_settler.rs`.
- [ ] `encode_settle_calldata()` calldata matches contract ABI (verified via `cast call --data` in CI).
- [ ] End-to-end test: governed execution → `finalize()` → `settle()` → `isSettled()` returns `true`.
- [ ] Settlement is idempotent: duplicate `settle()` calls succeed without reverting.

---

## 11. Open Questions and Future Extensions

### 11.1 Checkpointed Sub-Sessions for Long-Running Agents

Long-running agents (multi-hour workflows, RPA bots) may exceed `MAX_TRACE_RECEIPTS`. The recommended approach is **periodic checkpointing**: every K receipts, finalize the current trace into an interim `PoGEAuditRoot`, settle it on-chain, and start a new `PoGEInterceptor` with a **chained warrant** whose `scope_cbor` includes the previous session's `merkle_root` as a parent pointer. This creates a linked-list of audit roots on-chain, each covering K host-calls, together forming a complete session audit.

### 11.2 TEE-Based Host Attestation

Placing the `PoGEInterceptor` inside an Intel TDX or AMD SEV-SNP enclave and including the enclave measurement report in the `PoGEAuditRoot` would close the host-integrity gap identified in §8.3. The Kernel would verify the enclave quote before accepting an audit root as fully trusted. This is under evaluation pending hardware availability on Base-layer cloud infrastructure.

### 11.3 BLAKE3 as an Optional Hash Backend

BLAKE3 achieves ~3–5× higher throughput than SHA-256 on x86-64 with AVX-512 (~10 GB/s vs ~1.8 GB/s). For deployments hashing large LLM payloads (≥ 100 KiB per call), a `--feature blake3-receipts` build flag could substitute BLAKE3 in `receipt_for()`. The EVM settlement layer would still use SHA-256 for the Merkle root (EVM `sha256` precompile at address `0x02` makes SHA-256 cheap on-chain). This hybrid approach requires a second domain tag namespace (`POGE_RECEIPT_B3_v1`) and versioning in the `PoGEAuditRoot`.

### 11.4 ZK Compression of Trace Proofs

For verifiers who require only a subset of receipts (e.g., "prove that call #412 was an LLM inference to model X with output Y"), a succinct proof system (e.g., a Groth16 or PLONK circuit over the Merkle path) could compress a 32-node Merkle proof into a constant-size ≈ 192-byte ZK proof. This is a research-track item; the PoGE receipt and Merkle construction are ZK-friendly (SHA-256 circuits exist in both `circom` and `halo2`).

### 11.5 Cross-Shard Warrant Aggregation

In a multi-kernel deployment (sharded AI workloads across Meridian zones), multiple `KernelWarrant`s from different kernel shards may govern sub-tasks of a single logical workflow. An **aggregate audit root**—a Merkle tree of individual session Merkle roots—would provide a single on-chain commitment for the entire workflow. The `PoGEAuditRoot::merkle_root` field nests cleanly as a leaf in such a meta-tree.

---

## 12. References

1. **Wasmtime Linker API** — Bytecode Alliance, `wasmtime::Linker::func_wrap` documentation, https://docs.rs/wasmtime
2. **SHA-256 Specification** — NIST FIPS PUB 180-4, *Secure Hash Standard*, August 2015
3. **Merkle Trees** — R. C. Merkle, "A Digital Signature Based on a Conventional Encryption Function," CRYPTO 1987
4. **Domain Separation in Hash Functions** — Bernstein & Lange, "Non-uniform cracks in the concrete," 2012; NIST SP 800-185
5. **Length-Extension Attack Prevention** — Bhargavan & Leurent, "On the Practical (In-)Security of 64-bit Block Ciphers," 2016 (motivates length-prefix framing)
6. **OpenZeppelin MerkleProof** — OpenZeppelin Contracts v5.x, `utils/cryptography/MerkleProof.sol`
7. **EVM ABI Encoding** — Ethereum Foundation, *Contract ABI Specification*, https://docs.soliditylang.org/en/v0.8.24/abi-spec.html
8. **Base Sepolia Testnet** — Coinbase, Chain ID 84532, https://sepolia.basescan.org
9. **Intel TDX Remote Attestation** — Intel Corporation, *Trust Domain Extensions (TDX) Module Architecture Specification*, Revision 1.5, 2023
10. **BLAKE3** — O'Connor et al., "BLAKE3: one function, fast everywhere," 2020, https://github.com/BLAKE3-team/BLAKE3-specs
11. **NIST AI RMF** — National Institute of Standards and Technology, *AI Risk Management Framework*, NIST AI 100-1, 2023
12. **Groth16** — Groth, "On the Size of Pairing-Based Non-interactive Arguments," EUROCRYPT 2016
13. **sha2 Rust crate** — RustCrypto, https://docs.rs/sha2
14. **ethabi Rust crate** — Parity Technologies, https://docs.rs/ethabi

---

*End of RFC-MERIDIAN-0001. All section numbers, type signatures, and test criteria are normative. Implementation MUST match this specification; deviations require an RFC amendment with a new revision number.*

*Copyright 2026 Meridian. All rights reserved. Distribution of this document is governed by the Meridian Confidential Information Policy.*
