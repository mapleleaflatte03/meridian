use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::PoGEAuditRoot;

/// Supported zk proof backends for PoGE settlement preparation.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ZkProofBackend {
    Sp1,
}

impl ZkProofBackend {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Sp1 => "sp1",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParseZkProofBackendError {
    pub raw: String,
}

impl std::fmt::Display for ParseZkProofBackendError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "unknown zk proof backend '{}'; supported backends: sp1",
            self.raw
        )
    }
}

impl std::error::Error for ParseZkProofBackendError {}

impl std::str::FromStr for ZkProofBackend {
    type Err = ParseZkProofBackendError;

    fn from_str(raw: &str) -> Result<Self, Self::Err> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "sp1" => Ok(Self::Sp1),
            _ => Err(ParseZkProofBackendError {
                raw: raw.trim().to_string(),
            }),
        }
    }
}

/// A bounded zk proof artifact prepared from a finalized PoGE audit root.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ZkPoGEProof {
    pub proof_backend: ZkProofBackend,
    pub proof_mode: String,
    pub proof_id: String,
    pub verification_status: String,
    pub warrant_binding_status: String,
    pub warrant_id_hex: String,
    pub merkle_root_hex: String,
    pub witness_digest_hex: String,
    pub trace_len: u32,
    pub epoch_start_ms: u64,
    pub epoch_end_ms: u64,
    pub session_label: String,
}

impl ZkPoGEProof {
    pub fn prepare(
        root: &PoGEAuditRoot,
        warrant_binding_status: &str,
        backend: ZkProofBackend,
    ) -> Self {
        match backend {
            ZkProofBackend::Sp1 => Self::prepare_sp1(root, warrant_binding_status),
        }
    }

    pub fn prepare_sp1(root: &PoGEAuditRoot, warrant_binding_status: &str) -> Self {
        let mut proof_id_hasher = Sha256::new();
        proof_id_hasher.update(b"POGE_ZK_PROOF_ID_v1\x00");
        proof_id_hasher.update(root.witness_digest());
        proof_id_hasher.update(root.merkle_root);
        proof_id_hasher.update(ZkProofBackend::Sp1.as_str().as_bytes());
        let proof_id_hex = hex::encode(proof_id_hasher.finalize());
        Self {
            proof_backend: ZkProofBackend::Sp1,
            proof_mode: "bounded_adapter".to_string(),
            proof_id: format!("zkp_{}", &proof_id_hex[..16]),
            verification_status: "witness_bound".to_string(),
            warrant_binding_status: warrant_binding_status.to_string(),
            warrant_id_hex: format!("0x{}", hex::encode(root.warrant_id)),
            merkle_root_hex: root.merkle_root_hex(),
            witness_digest_hex: root.witness_digest_hex(),
            trace_len: root.trace_len,
            epoch_start_ms: root.epoch_start_ms,
            epoch_end_ms: root.epoch_end_ms,
            session_label: root.session_label.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_audit_root() -> PoGEAuditRoot {
        PoGEAuditRoot {
            merkle_root: [0x11; 32],
            warrant_id: [0x22; 32],
            trace_len: 3,
            epoch_start_ms: 1_700_000_000_100,
            epoch_end_ms: 1_700_000_000_900,
            module_digest: [0x33; 32],
            session_label: "shadow:org_demo:agent_atlas:research".to_string(),
        }
    }

    #[test]
    fn parse_backend_accepts_sp1() {
        let parsed = "sp1".parse::<ZkProofBackend>().expect("parse sp1");
        assert_eq!(parsed, ZkProofBackend::Sp1);
    }

    #[test]
    fn parse_backend_rejects_unknown_values() {
        let error = "risc0"
            .parse::<ZkProofBackend>()
            .expect_err("unknown backend should fail");
        assert!(
            error.to_string().contains("supported backends: sp1"),
            "{}",
            error
        );
    }

    #[test]
    fn prepare_sp1_is_deterministic() {
        let root = sample_audit_root();
        let first = ZkPoGEProof::prepare(&root, "verified", ZkProofBackend::Sp1);
        let second = ZkPoGEProof::prepare_sp1(&root, "verified");
        assert_eq!(first.proof_id, second.proof_id);
        assert_eq!(first.witness_digest_hex, second.witness_digest_hex);
        assert_eq!(first.merkle_root_hex, second.merkle_root_hex);
        assert_eq!(first.proof_backend, ZkProofBackend::Sp1);
    }
}
