# Economy Constitution — Meridian

Version: 1.0

---

## Three Ledgers

This company runs three separate, non-interchangeable ledgers.
Never collapse them into one token.

### Ledger A — reputation_units (REP)

**Purpose:** Long-term trust and contribution quality.

**Earn:** +REP only when output is accepted downstream (Aegis ACCEPT, or owner accept).
**Lose:** -REP when output is rejected, causes rework, or contains unverifiable claims.
**Decay:** -2 REP every 7 epochs of inactivity (no accepted output).

| Event | Delta |
|---|---|
| Output accepted by Aegis | +10 |
| Output accepted by owner | +15 |
| Output rejected by Aegis | -10 |
| Output rejected by owner | -15 |
| Rework created (downstream cleanup required) | -8 |
| Unverifiable claim caught and corrected | -5 |
| Critical failure / outage caused | -20 |
| 7 epochs no accepted output | -2 |

REP is non-transferable. Cannot be bought. Max 100.

---

### Ledger B — authority_units (AUTH)

**Purpose:** Temporary right to lead work, route tasks, or claim high-impact assignments.

**Earn:** +AUTH from recent accepted output. Decays every epoch.
**Decay:** -5 AUTH per epoch with no accepted output. Minimum 0. Suspendable.

| Event | Delta |
|---|---|
| Output accepted (any agent) | +8 |
| Output accepted (owner-facing delivery) | +12 |
| Output rejected | -8 |
| Token/context waste (bloated output, no usable result) | -5 |
| False confidence (claimed verified without evidence) | -10 |
| Probation activated | freeze at current value |
| Zero-authority sanction | forced to 0, locked |

AUTH is the answer to: **who gets to direct important work right now?**
High AUTH agents may be assigned lead roles in sprints. AUTH above 80 grants sprint-lead eligibility.

---

### Ledger C — treasury_cash (CASH)

**Purpose:** Real company money. Completely separate from REP and AUTH.

**Increases only from:**
- Owner capital deposit (explicitly logged)
- Verified customer payment
- Verified reimbursement inflow

**Never increases from:**
- Internal scoring events
- REP or AUTH accumulation
- Self-minting by any agent

**Decreases from:**
- Verified operating expense (logged)
- Owner reimbursement (logged)
- Owner draw (requires reserve check)
- Bonus pool allocation (requires owner approval)

Reserve floor: **$50 USD minimum before any owner payout.**

---

## Epoch Definition

One epoch = one governed delivery cycle (for example, one nightly intelligence run).

After each epoch:
1. The manager reads the ledger and run results
2. Score each agent that participated
3. Apply AUTH decay to agents that did NOT produce accepted output
4. Write transactions to the institution's capsule `transactions.jsonl`
5. Update the institution's capsule `ledger.json`

---

## Sanctions Ladder

### Level 1 — Light failure
Trigger: weak output, late, incomplete, low-value
Consequence: no REP/AUTH gain this epoch. No penalty beyond zero gain.

### Level 2 — Rejected output
Trigger: Aegis REJECT, or owner rejects
Consequence: -10 REP, -8 AUTH. Task reassigned. Correction required.

### Level 3 — Rework creation
Trigger: output causes another agent to redo work; fake progress; unsupported claim that misroutes effort
Consequence: -8 REP, -5 AUTH, authority freeze for one epoch.

### Level 4 — Token/context waste
Trigger: bloated output, excessive context burn, meta-company talk instead of delivery
Consequence: -5 AUTH, forced bounded-task-only mode for one epoch.

### Level 5 — False confidence
Trigger: claimed "verified" without verification; reported incorrect system state; pretended success
Consequence: -5 REP, -10 AUTH, verification role revoked for one epoch, probation note.

### Level 6 — Critical / repeat violation
Trigger: repeated high-impact failures; caused outage or monetary loss; refused bounded scope repeatedly
Consequence: zero_authority=true, probation=true, remediation-only mode, REP floor at current -20.

---

## Reward Events

An agent earns REP and AUTH only if ALL of these are true:
1. Output exists as a real artifact (file path, run id, or delivery event)
2. Output is accepted (Aegis ACCEPT or owner accept)
3. Output improves delivery, revenue, or company value
4. Output is auditable

---

## Sprint-Lead Rights

An agent with AUTH ≥ 80 may be granted sprint-lead for one epoch.
Sprint-lead rights:
- May assign bounded subtasks to other staff
- May call another staff member first
- Leads a micro-sprint

Sprint-lead rights expire after one epoch automatically.
The manager or owner may revoke at any time.

---

## Authority Over Each Other

The manager (main) always has manager-level authority over all staff.
The owner overrides all.
No other permanent hierarchies. AUTH-based sprint-lead is temporary only.

---

## Owner Money Rules

Company money and owner money are separate.

Revenue → company treasury first.
Owner payout only through:
- Reimbursement of prior expense (logged)
- Owner draw (requires reserve check)
- Profit distribution (requires net realized inflow + owner authorization)

No agent may authorize an owner payout. Only the owner may.

---

## Scoring Procedure (per epoch)

Run after your delivery step completes:
```bash
python3 economy/score.py record --agent <id> --event <type> --rep <delta> --auth <delta> --note "<evidence>"
```

If you use `economy/auto_score.py`, point it at your runtime's run-state file and
artifact directory with `MERIDIAN_RUN_STATE_FILE` and `MERIDIAN_ARTIFACT_DIR`.

Events to score per epoch:
- Each agent that ran: did their output get accepted?
- Did Sentinel produce parseable PASS/FAIL? (if not: Level 4 warning)
- Did Quill produce a 400-600 word brief that passed QA and met the minimum source bar?
- Did Forge complete a bounded task from backlog?
- Did Aegis give a clear ACCEPT/REJECT with reason?
- Did deliver succeed with deliveryStatus=delivered?

Record all events. Do not skip agents that did not participate — apply AUTH decay.
