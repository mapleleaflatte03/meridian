#!/usr/bin/env python3
"""
Minimal founder sales cockpit for Meridian.

Keeps local lead state in company/leads.json (gitignored) and ships a sample schema in
company/leads.json.sample.

Usage:
  python3 company/lead_tracker.py summary
  python3 company/lead_tracker.py add --name "Jane Doe" --company "Acme" --role "PMM"
  python3 company/lead_tracker.py list
  python3 company/lead_tracker.py show --lead lead_abc123
  python3 company/lead_tracker.py set-stage --lead lead_abc123 --stage replied
  python3 company/lead_tracker.py note --lead lead_abc123 --text "Asked for demo"
  python3 company/lead_tracker.py next
"""
import argparse
import datetime as dt
import json
import os
import uuid


COMPANY_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(COMPANY_DIR, "leads.json")
SAMPLE_FILE = os.path.join(COMPANY_DIR, "leads.json.sample")
STAGE_ORDER = [
    "new",
    "contacted",
    "replied",
    "scoping",
    "pilot_active",
    "waiting_feedback",
    "negotiating",
    "won",
    "lost",
]
ACTIVE_STAGES = {"new", "contacted", "replied", "scoping", "pilot_active", "waiting_feedback", "negotiating"}


def now_ts():
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_state():
    return {
        "_meta": {
            "schema_version": 1,
            "owner": "son",
            "description": "Local lead tracker state for founder-led pilot outreach.",
            "updated_at": now_ts(),
        },
        "stage_order": STAGE_ORDER,
        "leads": [],
    }


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    if os.path.exists(SAMPLE_FILE):
        with open(SAMPLE_FILE) as f:
            data = json.load(f)
        data["_meta"]["updated_at"] = now_ts()
        return data
    return _default_state()


def save_state(state):
    state.setdefault("_meta", {})
    state["_meta"]["updated_at"] = now_ts()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def ensure_stage(stage):
    if stage not in STAGE_ORDER:
        raise SystemExit(f"Unknown stage '{stage}'. Valid: {', '.join(STAGE_ORDER)}")


def find_lead(state, lead_id):
    for lead in state.get("leads", []):
        if lead["id"] == lead_id:
            return lead
    raise SystemExit(f"Lead not found: {lead_id}")


def format_lead_row(lead):
    return (
        f"{lead['id']:<16} "
        f"{lead.get('company','-')[:18]:<18} "
        f"{lead.get('name','-')[:16]:<16} "
        f"{lead.get('stage','-'):<16} "
        f"{lead.get('next_action','-')[:28]:<28} "
        f"{lead.get('last_touch_at','-')[:10]}"
    )


def add_cmd(args):
    state = load_state()
    lead_id = "lead_" + uuid.uuid4().hex[:8]
    lead = {
        "id": lead_id,
        "name": args.name,
        "company": args.company,
        "role": args.role or "",
        "stage": "new",
        "source": args.source or "",
        "contact_channel": args.contact_channel or "",
        "contact_handle": args.contact_handle or "",
        "priority": args.priority,
        "fit_score": args.fit_score,
        "competitors": args.competitors.split(",") if args.competitors else [],
        "topics": args.topics.split(",") if args.topics else [],
        "notes": [],
        "next_action": args.next_action or "Send first demo link",
        "created_at": now_ts(),
        "last_touch_at": "",
    }
    state["leads"].append(lead)
    save_state(state)
    print(f"Added {lead_id} for {args.company} / {args.name}")


def list_cmd(args):
    state = load_state()
    leads = list(state.get("leads", []))
    if args.active_only:
        leads = [l for l in leads if l.get("stage") in ACTIVE_STAGES]
    if args.stage:
        leads = [l for l in leads if l.get("stage") == args.stage]
    sort_key = {
        "priority": lambda l: (-int(l.get("priority", 3)), l.get("company", "")),
        "updated": lambda l: (l.get("last_touch_at") or l.get("created_at") or "", l.get("company", "")),
        "stage": lambda l: (STAGE_ORDER.index(l.get("stage", "new")), l.get("company", "")),
    }[args.sort]
    leads = sorted(leads, key=sort_key, reverse=args.sort == "updated")
    print(f"{'ID':<16} {'Company':<18} {'Name':<16} {'Stage':<16} {'Next action':<28} {'Last touch'}")
    print("-" * 110)
    for lead in leads:
        print(format_lead_row(lead))
    if not leads:
        print("No leads.")


def show_cmd(args):
    state = load_state()
    lead = find_lead(state, args.lead)
    print(json.dumps(lead, indent=2))


def set_stage_cmd(args):
    ensure_stage(args.stage)
    state = load_state()
    lead = find_lead(state, args.lead)
    lead["stage"] = args.stage
    if args.next_action is not None:
        lead["next_action"] = args.next_action
    lead["last_touch_at"] = now_ts()
    save_state(state)
    print(f"{lead['id']} -> {args.stage}")


def note_cmd(args):
    state = load_state()
    lead = find_lead(state, args.lead)
    lead.setdefault("notes", []).append({"at": now_ts(), "text": args.text})
    if args.next_action is not None:
        lead["next_action"] = args.next_action
    lead["last_touch_at"] = now_ts()
    save_state(state)
    print(f"Noted {lead['id']}")


def touch_cmd(args):
    state = load_state()
    lead = find_lead(state, args.lead)
    lead["last_touch_at"] = now_ts()
    if args.channel:
        lead["last_touch_channel"] = args.channel
    if args.next_action is not None:
        lead["next_action"] = args.next_action
    save_state(state)
    print(f"Touched {lead['id']}")


def summary_cmd(args):
    state = load_state()
    leads = state.get("leads", [])
    counts = {stage: 0 for stage in STAGE_ORDER}
    for lead in leads:
        counts[lead.get("stage", "new")] = counts.get(lead.get("stage", "new"), 0) + 1
    print("Meridian lead pipeline")
    print(f"Total leads: {len(leads)}")
    for stage in STAGE_ORDER:
        if counts.get(stage):
            print(f"- {stage}: {counts[stage]}")
    active = [l for l in leads if l.get("stage") in ACTIVE_STAGES]
    if active:
        hottest = sorted(active, key=lambda l: (-int(l.get("priority", 3)), STAGE_ORDER.index(l.get("stage", "new"))))[0]
        print("")
        print("Best next lead:")
        print(format_lead_row(hottest))


def next_cmd(args):
    state = load_state()
    active = [l for l in state.get("leads", []) if l.get("stage") in ACTIVE_STAGES]
    if not active:
        print("No active leads.")
        return
    ranked = sorted(
        active,
        key=lambda l: (
            -int(l.get("priority", 3)),
            STAGE_ORDER.index(l.get("stage", "new")),
            l.get("last_touch_at") or l.get("created_at") or "",
        ),
    )
    lead = ranked[0]
    print("Next lead to move:")
    print(format_lead_row(lead))
    if lead.get("notes"):
        print("")
        print("Latest note:")
        print(f"- {lead['notes'][-1]['at']}: {lead['notes'][-1]['text']}")


def init_cmd(args):
    state = load_state()
    if os.path.exists(STATE_FILE) and not args.force:
        print(f"{STATE_FILE} already exists")
        return
    save_state(state)
    print(f"Initialized {STATE_FILE}")


def main():
    p = argparse.ArgumentParser(description="Founder lead tracker for Meridian")
    sub = p.add_subparsers(dest="command")

    init_p = sub.add_parser("init")
    init_p.add_argument("--force", action="store_true")

    add_p = sub.add_parser("add")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--company", required=True)
    add_p.add_argument("--role")
    add_p.add_argument("--source")
    add_p.add_argument("--contact-channel")
    add_p.add_argument("--contact-handle")
    add_p.add_argument("--priority", type=int, default=3)
    add_p.add_argument("--fit-score", type=int, default=3)
    add_p.add_argument("--competitors")
    add_p.add_argument("--topics")
    add_p.add_argument("--next-action")

    list_p = sub.add_parser("list")
    list_p.add_argument("--active-only", action="store_true")
    list_p.add_argument("--stage")
    list_p.add_argument("--sort", choices=["priority", "updated", "stage"], default="priority")

    show_p = sub.add_parser("show")
    show_p.add_argument("--lead", required=True)

    stage_p = sub.add_parser("set-stage")
    stage_p.add_argument("--lead", required=True)
    stage_p.add_argument("--stage", required=True)
    stage_p.add_argument("--next-action")

    note_p = sub.add_parser("note")
    note_p.add_argument("--lead", required=True)
    note_p.add_argument("--text", required=True)
    note_p.add_argument("--next-action")

    touch_p = sub.add_parser("touch")
    touch_p.add_argument("--lead", required=True)
    touch_p.add_argument("--channel")
    touch_p.add_argument("--next-action")

    sub.add_parser("summary")
    sub.add_parser("next")

    args = p.parse_args()
    if args.command == "init":
        init_cmd(args)
    elif args.command == "add":
        add_cmd(args)
    elif args.command == "list":
        list_cmd(args)
    elif args.command == "show":
        show_cmd(args)
    elif args.command == "set-stage":
        set_stage_cmd(args)
    elif args.command == "note":
        note_cmd(args)
    elif args.command == "touch":
        touch_cmd(args)
    elif args.command == "summary":
        summary_cmd(args)
    elif args.command == "next":
        next_cmd(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
