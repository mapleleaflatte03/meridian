use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

/// Result type for reservation operations.
pub type ReservationResult<T> = Result<T, String>;

/// State of a job reservation.
#[derive(Clone, Debug, PartialEq)]
pub enum ReservationState {
    Reserved,
    Acked,
    Nacked,
    Expired,
}

impl ReservationState {
    fn as_str(&self) -> &'static str {
        match self {
            ReservationState::Reserved => "reserved",
            ReservationState::Acked => "acked",
            ReservationState::Nacked => "nacked",
            ReservationState::Expired => "expired",
        }
    }

    fn from_str(s: &str) -> ReservationResult<Self> {
        match s {
            "reserved" => Ok(ReservationState::Reserved),
            "acked" => Ok(ReservationState::Acked),
            "nacked" => Ok(ReservationState::Nacked),
            "expired" => Ok(ReservationState::Expired),
            other => Err(format!("unknown reservation state: {}", other)),
        }
    }
}

/// A single job reservation record.
#[derive(Clone, Debug, PartialEq)]
pub struct JobReservation {
    pub job_id: String,
    pub reservation_id: String,
    pub reserver_id: String,
    pub lease_started_at: u64,
    pub lease_duration_secs: u64,
    pub state: ReservationState,
}

impl JobReservation {
    fn to_json(&self) -> String {
        format!(
            "{{\"job_id\":{},\"reservation_id\":{},\"reserver_id\":{},\"lease_started_at\":{},\"lease_duration_secs\":{},\"state\":{}}}",
            json_string(&self.job_id),
            json_string(&self.reservation_id),
            json_string(&self.reserver_id),
            self.lease_started_at,
            self.lease_duration_secs,
            json_string(self.state.as_str()),
        )
    }

    fn from_json(raw: &str) -> ReservationResult<Self> {
        let job_id =
            extract_json_string(raw, "\"job_id\"").ok_or_else(|| "job_id missing".to_string())?;
        let reservation_id = extract_json_string(raw, "\"reservation_id\"")
            .unwrap_or_else(|| format!("res_{}", job_id));
        let reserver_id = extract_json_string(raw, "\"reserver_id\"")
            .ok_or_else(|| "reserver_id missing".to_string())?;
        let lease_started_at = extract_json_u64(raw, "\"lease_started_at\"")
            .ok_or_else(|| "lease_started_at missing".to_string())?;
        let lease_duration_secs = extract_json_u64(raw, "\"lease_duration_secs\"")
            .ok_or_else(|| "lease_duration_secs missing".to_string())?;
        let state_str =
            extract_json_string(raw, "\"state\"").ok_or_else(|| "state missing".to_string())?;
        let state = ReservationState::from_str(&state_str)?;
        Ok(JobReservation {
            job_id,
            reservation_id,
            reserver_id,
            lease_started_at,
            lease_duration_secs,
            state,
        })
    }
}

/// Ledger holding all job reservations keyed by job_id.
#[derive(Clone, Debug)]
pub struct ReservationLedger {
    pub reservations: BTreeMap<String, JobReservation>,
}

impl ReservationLedger {
    pub fn new() -> Self {
        ReservationLedger {
            reservations: BTreeMap::new(),
        }
    }

    fn to_json(&self) -> String {
        let entries: Vec<String> = self.reservations.values().map(|r| r.to_json()).collect();
        format!("{{\"reservations\":[{}]}}", entries.join(","))
    }

    fn from_json(raw: &str) -> ReservationResult<Self> {
        let mut ledger = ReservationLedger::new();
        // Find the array contents between [ and ]
        let arr_start = raw
            .find('[')
            .ok_or_else(|| "missing [ in ledger json".to_string())?;
        let arr_end = raw
            .rfind(']')
            .ok_or_else(|| "missing ] in ledger json".to_string())?;
        let arr_body = &raw[arr_start + 1..arr_end];
        if arr_body.trim().is_empty() {
            return Ok(ledger);
        }
        // Split on top-level objects by tracking brace depth
        for obj_str in split_json_objects(arr_body) {
            let reservation = JobReservation::from_json(&obj_str)?;
            ledger
                .reservations
                .insert(reservation.job_id.clone(), reservation);
        }
        Ok(ledger)
    }
}

/// Reserve a job. Fails if the job is already reserved (in Reserved state).
pub fn reserve_job(
    ledger: &mut ReservationLedger,
    job_id: &str,
    reserver_id: &str,
    duration: u64,
) -> ReservationResult<JobReservation> {
    if let Some(existing) = ledger.reservations.get(job_id) {
        if existing.state == ReservationState::Reserved {
            return Err(format!(
                "job {} is already reserved by {}",
                job_id, existing.reserver_id
            ));
        }
    }
    let now = epoch_now();
    let reservation = JobReservation {
        job_id: job_id.to_string(),
        reservation_id: format!("res_{}_{}", job_id, now),
        reserver_id: reserver_id.to_string(),
        lease_started_at: now,
        lease_duration_secs: duration,
        state: ReservationState::Reserved,
    };
    ledger
        .reservations
        .insert(job_id.to_string(), reservation.clone());
    Ok(reservation)
}

/// Acknowledge a reserved job. The reserver_id must match.
pub fn ack_job(
    ledger: &mut ReservationLedger,
    job_id: &str,
    reserver_id: &str,
) -> ReservationResult<()> {
    let reservation = ledger
        .reservations
        .get_mut(job_id)
        .ok_or_else(|| format!("no reservation for job {}", job_id))?;
    if reservation.reserver_id != reserver_id {
        return Err(format!(
            "reserver mismatch: expected {}, got {}",
            reservation.reserver_id, reserver_id
        ));
    }
    if reservation.state != ReservationState::Reserved {
        return Err(format!(
            "cannot ack job {} in state {:?}",
            job_id, reservation.state
        ));
    }
    reservation.state = ReservationState::Acked;
    Ok(())
}

/// Nack a reserved job, freeing it. The reserver_id must match.
pub fn nack_job(
    ledger: &mut ReservationLedger,
    job_id: &str,
    reserver_id: &str,
) -> ReservationResult<()> {
    let reservation = ledger
        .reservations
        .get_mut(job_id)
        .ok_or_else(|| format!("no reservation for job {}", job_id))?;
    if reservation.reserver_id != reserver_id {
        return Err(format!(
            "reserver mismatch: expected {}, got {}",
            reservation.reserver_id, reserver_id
        ));
    }
    if reservation.state != ReservationState::Reserved {
        return Err(format!(
            "cannot nack job {} in state {:?}",
            job_id, reservation.state
        ));
    }
    reservation.state = ReservationState::Nacked;
    Ok(())
}

/// Expire all reservations whose lease has elapsed. Returns freed job IDs.
pub fn expire_stale(ledger: &mut ReservationLedger, now_epoch: u64) -> Vec<String> {
    let mut freed = Vec::new();
    for (job_id, reservation) in ledger.reservations.iter_mut() {
        if reservation.state == ReservationState::Reserved {
            let expiry = reservation.lease_started_at + reservation.lease_duration_secs;
            if now_epoch >= expiry {
                reservation.state = ReservationState::Expired;
                freed.push(job_id.clone());
            }
        }
    }
    freed
}

/// Save the ledger to a JSON file.
pub fn save_ledger(ledger: &ReservationLedger, path: &Path) -> ReservationResult<()> {
    let json = ledger.to_json();
    fs::write(path, json).map_err(|e| e.to_string())
}

/// Load a ledger from a JSON file.
pub fn load_ledger(path: &Path) -> ReservationResult<ReservationLedger> {
    let contents = fs::read_to_string(path).map_err(|e| e.to_string())?;
    ReservationLedger::from_json(&contents)
}

// --- Internal helpers ---

fn json_string(input: &str) -> String {
    format!("{:?}", input)
}

fn extract_json_string(section: &str, key: &str) -> Option<String> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let first_quote = after.find('"')?;
    let rest = &after[first_quote + 1..];
    let end_quote = rest.find('"')?;
    Some(rest[..end_quote].to_string())
}

fn extract_json_u64(section: &str, key: &str) -> Option<u64> {
    let idx = section.find(key)?;
    let after = &section[idx + key.len()..];
    let colon = after.find(':')?;
    let rest = after[colon + 1..].trim_start();
    let end = rest
        .find([',', '}', '\n'])
        .unwrap_or(rest.len());
    rest[..end].trim().parse::<u64>().ok()
}

fn split_json_objects(body: &str) -> Vec<String> {
    let mut objects = Vec::new();
    let mut depth = 0;
    let mut start = None;
    for (i, c) in body.char_indices() {
        match c {
            '{' => {
                if depth == 0 {
                    start = Some(i);
                }
                depth += 1;
            }
            '}' => {
                depth -= 1;
                if depth == 0 {
                    if let Some(s) = start {
                        objects.push(body[s..=i].to_string());
                    }
                    start = None;
                }
            }
            _ => {}
        }
    }
    objects
}

fn epoch_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn reserve_ack_lifecycle() {
        let mut ledger = ReservationLedger::new();
        let res = reserve_job(&mut ledger, "job_1", "agent_atlas", 300).unwrap();
        assert_eq!(res.state, ReservationState::Reserved);
        assert_eq!(res.job_id, "job_1");
        assert!(res.reservation_id.starts_with("res_job_1_"));

        ack_job(&mut ledger, "job_1", "agent_atlas").unwrap();
        assert_eq!(
            ledger.reservations.get("job_1").unwrap().state,
            ReservationState::Acked
        );
    }

    #[test]
    fn reserve_nack_frees_job() {
        let mut ledger = ReservationLedger::new();
        reserve_job(&mut ledger, "job_2", "agent_forge", 60).unwrap();
        nack_job(&mut ledger, "job_2", "agent_forge").unwrap();
        assert_eq!(
            ledger.reservations.get("job_2").unwrap().state,
            ReservationState::Nacked
        );

        // After nack, another agent can reserve the same job
        let res2 = reserve_job(&mut ledger, "job_2", "agent_quill", 120).unwrap();
        assert_eq!(res2.reserver_id, "agent_quill");
        assert_eq!(res2.state, ReservationState::Reserved);
    }

    #[test]
    fn duplicate_reserve_rejected() {
        let mut ledger = ReservationLedger::new();
        reserve_job(&mut ledger, "job_3", "agent_atlas", 300).unwrap();
        let err = reserve_job(&mut ledger, "job_3", "agent_forge", 300);
        assert!(err.is_err());
        assert!(err.unwrap_err().contains("already reserved"));
    }

    #[test]
    fn expire_stale_frees_expired_leases() {
        let mut ledger = ReservationLedger::new();
        // Manually insert a reservation with a known start time
        ledger.reservations.insert(
            "job_old".to_string(),
            JobReservation {
                job_id: "job_old".to_string(),
                reservation_id: "res_job_old".to_string(),
                reserver_id: "agent_pulse".to_string(),
                lease_started_at: 1000,
                lease_duration_secs: 60,
                state: ReservationState::Reserved,
            },
        );
        ledger.reservations.insert(
            "job_fresh".to_string(),
            JobReservation {
                job_id: "job_fresh".to_string(),
                reservation_id: "res_job_fresh".to_string(),
                reserver_id: "agent_aegis".to_string(),
                lease_started_at: 1000,
                lease_duration_secs: 600,
                state: ReservationState::Reserved,
            },
        );

        let freed = expire_stale(&mut ledger, 1100);
        assert_eq!(freed, vec!["job_old".to_string()]);
        assert_eq!(
            ledger.reservations.get("job_old").unwrap().state,
            ReservationState::Expired
        );
        assert_eq!(
            ledger.reservations.get("job_fresh").unwrap().state,
            ReservationState::Reserved
        );
    }

    #[test]
    fn save_load_roundtrip() {
        let mut ledger = ReservationLedger::new();
        ledger.reservations.insert(
            "job_rt".to_string(),
            JobReservation {
                job_id: "job_rt".to_string(),
                reservation_id: "res_job_rt".to_string(),
                reserver_id: "agent_sentinel".to_string(),
                lease_started_at: 5000,
                lease_duration_secs: 120,
                state: ReservationState::Reserved,
            },
        );

        let dir = std::env::temp_dir().join("loom-shadow-reservation-test");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("ledger.json");

        save_ledger(&ledger, &path).unwrap();
        let loaded = load_ledger(&path).unwrap();

        assert_eq!(loaded.reservations.len(), 1);
        let r = loaded.reservations.get("job_rt").unwrap();
        assert_eq!(r.reserver_id, "agent_sentinel");
        assert_eq!(r.lease_started_at, 5000);
        assert_eq!(r.lease_duration_secs, 120);
        assert_eq!(r.state, ReservationState::Reserved);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn ack_wrong_reserver_rejected() {
        let mut ledger = ReservationLedger::new();
        reserve_job(&mut ledger, "job_x", "agent_atlas", 300).unwrap();
        let err = ack_job(&mut ledger, "job_x", "agent_forge");
        assert!(err.is_err());
        assert!(err.unwrap_err().contains("reserver mismatch"));
    }
}
