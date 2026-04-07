use serde_json::json;

pub type LoomResult<T> = Result<T, String>;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OutputGuardPolicy {
    pub allow_receipt_hashes: bool,
    pub allow_operator_diagnostics: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputGuardResult {
    pub raw_text: String,
    pub source_class: String,
    pub final_class: String,
    pub allowed: bool,
    pub display_text: String,
    pub deny_reason: Option<String>,
    pub redactions_applied: Vec<String>,
    pub detected_tokens: Vec<String>,
}

pub fn guard_user_visible_output(
    raw: &str,
    policy: &OutputGuardPolicy,
) -> LoomResult<OutputGuardResult> {
    let raw_text = raw.to_string();
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Ok(OutputGuardResult {
            raw_text,
            source_class: "empty".to_string(),
            final_class: "user_visible".to_string(),
            allowed: true,
            display_text: String::new(),
            deny_reason: None,
            redactions_applied: Vec::new(),
            detected_tokens: Vec::new(),
        });
    }

    let mut source_class = "user_visible".to_string();
    let mut final_class = "user_visible".to_string();
    let mut redactions_applied = Vec::new();
    let mut detected_tokens = Vec::new();

    if trimmed.eq_ignore_ascii_case("sleep") {
        detected_tokens.push("sleep".to_string());
        source_class = "internal_only".to_string();
        final_class = "blocked".to_string();
        return Ok(OutputGuardResult {
            raw_text,
            source_class,
            final_class,
            allowed: false,
            display_text: String::new(),
            deny_reason: Some("internal control token must not reach user channels".to_string()),
            redactions_applied,
            detected_tokens,
        });
    }

    for token in [
        "[SYSTEM: HEARTBEAT]",
        "SYSTEM: HEARTBEAT",
        "[🤔 THOUGHT]",
        "[THOUGHT]",
        "internal note",
        "planner note",
        "chain_of_thought",
    ] {
        if raw.contains(token) {
            detected_tokens.push(token.to_string());
            source_class = "internal_only".to_string();
        }
    }
    if source_class == "internal_only" {
        final_class = "blocked".to_string();
        return Ok(OutputGuardResult {
            raw_text,
            source_class,
            final_class,
            allowed: false,
            display_text: String::new(),
            deny_reason: Some(
                "internal planning or heartbeat text must not reach user channels".to_string(),
            ),
            redactions_applied,
            detected_tokens,
        });
    }

    if looks_like_operator_dump(trimmed) && !policy.allow_operator_diagnostics {
        detected_tokens.push("operator_dump".to_string());
        source_class = "operator_only".to_string();
        final_class = "blocked".to_string();
        return Ok(OutputGuardResult {
            raw_text,
            source_class,
            final_class,
            allowed: false,
            display_text: String::new(),
            deny_reason: Some(
                "operator diagnostics require explicit policy to reach user channels".to_string(),
            ),
            redactions_applied,
            detected_tokens,
        });
    }

    let mut display_text = extract_final_answer(raw).unwrap_or_else(|| raw.to_string());
    if display_text != raw {
        redactions_applied.push("extracted_final_answer".to_string());
    }

    let mut filtered_lines = Vec::new();
    let mut kept_receipt = false;
    for line in display_text.lines() {
        let trimmed_line = line.trim();
        if trimmed_line.is_empty() {
            filtered_lines.push(String::new());
            continue;
        }
        if is_receipt_line(trimmed_line) {
            detected_tokens.push("receipt_line".to_string());
            if policy.allow_receipt_hashes && !kept_receipt {
                kept_receipt = true;
                filtered_lines.push(render_receipt_line(trimmed_line));
                redactions_applied.push("receipt_compacted".to_string());
            } else {
                redactions_applied.push("receipt_removed".to_string());
            }
            continue;
        }
        if is_non_user_scaffold_line(trimmed_line) {
            redactions_applied.push("scaffold_removed".to_string());
            continue;
        }
        filtered_lines.push(line.to_string());
    }

    display_text = filtered_lines.join("\n");
    display_text = collapse_blank_lines(&display_text).trim().to_string();

    if display_text.is_empty() {
        final_class = "blocked".to_string();
        return Ok(OutputGuardResult {
            raw_text,
            source_class,
            final_class,
            allowed: false,
            display_text,
            deny_reason: Some("no user-safe content remained after filtering".to_string()),
            redactions_applied,
            detected_tokens,
        });
    }

    if kept_receipt {
        final_class = "dual_visible".to_string();
    }

    Ok(OutputGuardResult {
        raw_text,
        source_class,
        final_class,
        allowed: true,
        display_text,
        deny_reason: None,
        redactions_applied,
        detected_tokens,
    })
}

pub fn render_output_guard_human(result: &OutputGuardResult) -> String {
    format!(
        "allowed:             {}\nsource_class:        {}\nfinal_class:         {}\ndeny_reason:         {}\nredactions_applied:  {}\ndetected_tokens:     {}\noutput:\n{}\n",
        result.allowed,
        result.source_class,
        result.final_class,
        result
            .deny_reason
            .as_deref()
            .unwrap_or("(none)"),
        if result.redactions_applied.is_empty() {
            "(none)".to_string()
        } else {
            result.redactions_applied.join(",")
        },
        if result.detected_tokens.is_empty() {
            "(none)".to_string()
        } else {
            result.detected_tokens.join(",")
        },
        if result.display_text.is_empty() {
            "(empty)".to_string()
        } else {
            result.display_text.clone()
        }
    )
}

pub fn render_output_guard_json(result: &OutputGuardResult) -> String {
    serde_json::to_string_pretty(&json!({
        "allowed": result.allowed,
        "source_class": result.source_class,
        "final_class": result.final_class,
        "deny_reason": result.deny_reason,
        "redactions_applied": result.redactions_applied,
        "detected_tokens": result.detected_tokens,
        "display_text": result.display_text,
    }))
    .unwrap_or_else(|_| "{}".to_string())
        + "\n"
}

fn extract_final_answer(raw: &str) -> Option<String> {
    let markers = ["[✅ FINAL ANSWER]", "[FINAL ANSWER]"];
    for marker in markers {
        if let Some((_, remainder)) = raw.split_once(marker) {
            return Some(remainder.trim().to_string());
        }
    }
    None
}

fn looks_like_operator_dump(raw: &str) -> bool {
    let starts_like_data = raw.starts_with('{') || raw.starts_with('[');
    starts_like_data
        && [
            "capability",
            "host_calls",
            "worker_note",
            "executed_capability",
        ]
        .iter()
        .any(|token| raw.contains(token))
}

fn is_receipt_line(line: &str) -> bool {
    line.contains("[🛡️ PoGE PROTOCOL]")
        || line.contains("Cryptographic Audit Root Settled")
        || line.contains("Trace Length:")
}

fn render_receipt_line(line: &str) -> String {
    if let Some(hash) = extract_receipt_hash(line) {
        return format!("[PoGE Receipt] {}", hash);
    }
    "[PoGE Receipt] present".to_string()
}

fn extract_receipt_hash(line: &str) -> Option<String> {
    line.split_whitespace()
        .find(|part| part.starts_with("0x"))
        .map(|part| part.to_string())
}

fn is_non_user_scaffold_line(line: &str) -> bool {
    [
        "[👤 USER GOAL]",
        "[🧠 USER GOAL]",
        "⚙️ Meridian Loom is governing your request...",
    ]
    .iter()
    .any(|token| line.contains(token))
}

fn collapse_blank_lines(input: &str) -> String {
    let mut collapsed = Vec::new();
    let mut previous_blank = false;
    for line in input.lines() {
        let is_blank = line.trim().is_empty();
        if is_blank && previous_blank {
            continue;
        }
        collapsed.push(line);
        previous_blank = is_blank;
    }
    collapsed.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sleep_is_blocked() {
        let result = guard_user_visible_output("SLEEP", &OutputGuardPolicy::default())
            .expect("guard result");
        assert!(!result.allowed);
        assert_eq!(result.final_class, "blocked");
        assert!(result.detected_tokens.iter().any(|token| token == "sleep"));
    }

    #[test]
    fn final_answer_is_extracted_and_receipts_removed() {
        let raw = "[👤 USER GOAL]\nhello\n[✅ FINAL ANSWER]\nXin chao\n[🛡️ PoGE PROTOCOL] Cryptographic Audit Root Settled: 0xabc\n";
        let result =
            guard_user_visible_output(raw, &OutputGuardPolicy::default()).expect("guard result");
        assert!(result.allowed);
        assert_eq!(result.display_text, "Xin chao");
        assert!(result
            .redactions_applied
            .iter()
            .any(|rule| rule == "extracted_final_answer"));
        assert!(result
            .redactions_applied
            .iter()
            .any(|rule| rule == "receipt_removed"));
    }

    #[test]
    fn receipt_can_be_compacted_when_allowed() {
        let raw =
            "[✅ FINAL ANSWER]\nDone\n[🛡️ PoGE PROTOCOL] Cryptographic Audit Root Settled: 0xabc\n";
        let result = guard_user_visible_output(
            raw,
            &OutputGuardPolicy {
                allow_receipt_hashes: true,
                allow_operator_diagnostics: false,
            },
        )
        .expect("guard result");
        assert!(result.allowed);
        assert!(result.display_text.contains("Done"));
        assert!(result.display_text.contains("[PoGE Receipt] 0xabc"));
        assert_eq!(result.final_class, "dual_visible");
    }

    #[test]
    fn operator_dump_is_blocked_by_default() {
        let raw = r#"{\n  \"capability\": \"loom.system.info.v1\",\n  \"host_calls\": [\"system.info\"]\n}"#;
        let result =
            guard_user_visible_output(raw, &OutputGuardPolicy::default()).expect("guard result");
        assert!(!result.allowed);
        assert_eq!(result.source_class, "operator_only");
    }

    #[test]
    fn heartbeat_prompt_is_blocked() {
        let raw = "[SYSTEM: HEARTBEAT] Check your context and memory.";
        let result =
            guard_user_visible_output(raw, &OutputGuardPolicy::default()).expect("guard result");
        assert!(!result.allowed);
        assert_eq!(result.source_class, "internal_only");
    }
}
