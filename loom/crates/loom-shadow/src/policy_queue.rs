// policy_queue.rs — Queue partitioning by policy class
// Task 13 from LOOM_100_IMPROVEMENTS

use std::collections::{BTreeMap, VecDeque};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum PolicyClass {
    Standard,
    Privileged,
    BudgetHeavy,
    SanctionSensitive,
}

impl PolicyClass {
    pub fn label(&self) -> &'static str {
        match self {
            Self::Standard => "standard",
            Self::Privileged => "privileged",
            Self::BudgetHeavy => "budget_heavy",
            Self::SanctionSensitive => "sanction_sensitive",
        }
    }

    pub fn from_label(value: &str) -> Option<Self> {
        match value {
            "standard" => Some(Self::Standard),
            "privileged" => Some(Self::Privileged),
            "budget_heavy" => Some(Self::BudgetHeavy),
            "sanction_sensitive" => Some(Self::SanctionSensitive),
            _ => None,
        }
    }

    /// Priority order: SanctionSensitive > Privileged > BudgetHeavy > Standard
    fn priority(&self) -> u8 {
        match self {
            Self::SanctionSensitive => 3,
            Self::Privileged => 2,
            Self::BudgetHeavy => 1,
            Self::Standard => 0,
        }
    }

    pub fn all() -> &'static [PolicyClass] {
        &[
            Self::SanctionSensitive,
            Self::Privileged,
            Self::BudgetHeavy,
            Self::Standard,
        ]
    }
}

/// Classify an action into a policy lane based on its properties.
pub fn classify_action(action_type: &str, estimated_cost: f64, has_sanctions: bool) -> PolicyClass {
    if has_sanctions {
        return PolicyClass::SanctionSensitive;
    }
    if action_type == "admin" || action_type == "authority" || action_type == "court" {
        return PolicyClass::Privileged;
    }
    if estimated_cost > 1.0 {
        return PolicyClass::BudgetHeavy;
    }
    PolicyClass::Standard
}

pub struct PolicyQueue {
    lanes: BTreeMap<u8, VecDeque<String>>,
}

impl PolicyQueue {
    pub fn new() -> Self {
        let mut lanes = BTreeMap::new();
        for class in PolicyClass::all() {
            lanes.insert(class.priority(), VecDeque::new());
        }
        Self { lanes }
    }

    pub fn enqueue(&mut self, class: PolicyClass, job_id: String) {
        self.lanes
            .entry(class.priority())
            .or_default()
            .push_back(job_id);
    }

    /// Dequeue from the highest-priority non-empty lane.
    #[allow(dead_code)]
    pub fn dequeue_next(&mut self) -> Option<(PolicyClass, String)> {
        for class in PolicyClass::all() {
            if let Some(lane) = self.lanes.get_mut(&class.priority()) {
                if let Some(job_id) = lane.pop_front() {
                    return Some((*class, job_id));
                }
            }
        }
        None
    }

    pub fn queue_depths(&self) -> BTreeMap<String, usize> {
        let mut out = BTreeMap::new();
        for class in PolicyClass::all() {
            let depth = self
                .lanes
                .get(&class.priority())
                .map(|l| l.len())
                .unwrap_or(0);
            out.insert(class.label().to_string(), depth);
        }
        out
    }

    pub fn total_pending(&self) -> usize {
        self.lanes.values().map(|l| l.len()).sum()
    }
}

pub fn render_queue_depths_human(queue: &PolicyQueue) -> String {
    let depths = queue.queue_depths();
    let mut out = String::from("Meridian Loom // QUEUE DEPTHS\n=============================\n");
    for (label, depth) in &depths {
        out.push_str(&format!("{:<22} {}\n", label, depth));
    }
    out.push_str(&format!(
        "total                  {}\n",
        queue.total_pending()
    ));
    out
}

pub fn render_queue_depths_json(queue: &PolicyQueue) -> String {
    let depths = queue.queue_depths();
    let mut entries: Vec<String> = Vec::new();
    for (label, depth) in &depths {
        entries.push(format!("    \"{}\": {}", label, depth));
    }
    format!(
        "{{\n  \"queue_depths\": {{\n{}\n  }},\n  \"total\": {}\n}}",
        entries.join(",\n"),
        queue.total_pending()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_classify_standard() {
        assert_eq!(
            classify_action("research", 0.25, false),
            PolicyClass::Standard
        );
    }

    #[test]
    fn test_classify_budget_heavy() {
        assert_eq!(
            classify_action("research", 5.0, false),
            PolicyClass::BudgetHeavy
        );
    }

    #[test]
    fn test_classify_sanctioned() {
        assert_eq!(
            classify_action("research", 0.1, true),
            PolicyClass::SanctionSensitive
        );
    }

    #[test]
    fn test_classify_privileged() {
        assert_eq!(
            classify_action("admin", 0.1, false),
            PolicyClass::Privileged
        );
    }

    #[test]
    fn test_dequeue_priority_order() {
        let mut q = PolicyQueue::new();
        q.enqueue(PolicyClass::Standard, "job_std".to_string());
        q.enqueue(PolicyClass::Privileged, "job_priv".to_string());
        q.enqueue(PolicyClass::SanctionSensitive, "job_sanc".to_string());

        let (c1, j1) = q.dequeue_next().unwrap();
        assert_eq!(c1, PolicyClass::SanctionSensitive);
        assert_eq!(j1, "job_sanc");

        let (c2, j2) = q.dequeue_next().unwrap();
        assert_eq!(c2, PolicyClass::Privileged);
        assert_eq!(j2, "job_priv");

        let (c3, j3) = q.dequeue_next().unwrap();
        assert_eq!(c3, PolicyClass::Standard);
        assert_eq!(j3, "job_std");
    }

    #[test]
    fn test_queue_depths() {
        let mut q = PolicyQueue::new();
        q.enqueue(PolicyClass::Standard, "a".to_string());
        q.enqueue(PolicyClass::Standard, "b".to_string());
        q.enqueue(PolicyClass::BudgetHeavy, "c".to_string());
        let depths = q.queue_depths();
        assert_eq!(depths["standard"], 2);
        assert_eq!(depths["budget_heavy"], 1);
        assert_eq!(q.total_pending(), 3);
    }

    #[test]
    fn test_dequeue_empty() {
        let mut q = PolicyQueue::new();
        assert_eq!(q.dequeue_next(), None);
    }
}
