#!/usr/bin/env python3
"""
Scheduler truth helper with explicit separation of concerns.

`jobs.json` is configuration plus an embedded last-run cache. The per-job run
logs under `~/.meridian/cron/runs/*.jsonl` are the best source for the latest
recorded execution. Current host runtime health is a separate live check.

This helper reports those layers separately instead of flattening them into one
synthetic status record.

Usage:
  python3 scheduler_truth.py
  python3 scheduler_truth.py --job revenue-dashboard
  python3 scheduler_truth.py --job night-shift-deliver --json
"""
import argparse
import datetime as dt
import glob
import json
import os
import re

try:
    from loom_runtime_discovery import preferred_loom_bin, preferred_loom_root, run_loom_json
except ImportError:
    from .loom_runtime_discovery import preferred_loom_bin, preferred_loom_root, run_loom_json


CRON_DIR = os.path.expanduser('~/.meridian/cron')
JOBS_FILE = os.path.join(CRON_DIR, 'jobs.json')
RUNS_DIR = os.path.join(CRON_DIR, 'runs')
RECURRING_RUNS_DIR = os.path.join(preferred_loom_root(), 'state', 'recurring', 'runs')
DELIVERY_DIR = os.path.join(preferred_loom_root(), 'state', 'channels', 'delivery')


def _fmt_ms(ms):
    if not ms:
        return ''
    return dt.datetime.utcfromtimestamp(ms / 1000).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_jobs():
    if not os.path.exists(JOBS_FILE):
        return []
    with open(JOBS_FILE) as f:
        return json.load(f).get('jobs', [])


def load_run_entries(job_id):
    path = os.path.join(RUNS_DIR, f'{job_id}.jsonl')
    if not os.path.exists(path):
        return []
    entries = []
    with open(path) as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return entries


def latest_run_entry(job_id):
    entries = load_run_entries(job_id)
    if not entries:
        return None
    return max(entries, key=lambda entry: entry.get('ts', 0))


def load_recurring_run_entries(*job_keys):
    if not os.path.isdir(RECURRING_RUNS_DIR):
        return []
    keys = {str(key) for key in job_keys if key}
    entries = []
    for name in os.listdir(RECURRING_RUNS_DIR):
        if not name.endswith('.json'):
            continue
        path = os.path.join(RECURRING_RUNS_DIR, name)
        try:
            with open(path) as f:
                entry = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if str(entry.get('job_id') or '') in keys or str(entry.get('capability_name') or '') in keys:
            entries.append(entry)
    return entries


def latest_recurring_run_entry(*job_keys):
    entries = load_recurring_run_entries(*job_keys)
    if not entries:
        return None
    return max(
        entries,
        key=lambda entry: int(entry.get('completed_at') or entry.get('started_at') or 0),
    )


def load_delivery_record(delivery_id):
    if not delivery_id:
        return None
    matches = sorted(glob.glob(os.path.join(DELIVERY_DIR, f'*-{delivery_id}.json')))
    if not matches:
        return None
    path = matches[-1]
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _runtime_truth():
    response = run_loom_json(['doctor'], timeout=20)
    payload = response.get('payload') or []
    checks = payload.get('checks', payload) if isinstance(payload, dict) else payload
    critical = 0
    warn = 0
    for check in checks if isinstance(checks, list) else []:
        level = str(check.get('level', '')).upper()
        if level == 'CRITICAL':
            critical += 1
        elif level == 'WARN':
            warn += 1
    return {
        'loom_health_ok': bool(response.get('ok')) and critical == 0,
        'doctor_ok': bool(response.get('ok')),
        'critical_count': critical,
        'warn_count': warn,
        'binary_path': preferred_loom_bin(),
        'runtime_root': preferred_loom_root(),
    }


def _error_code(text):
    if not text:
        return ''
    try:
        parsed = json.loads(text)
    except Exception:
        return ''
    return parsed.get('detail', {}).get('code', '')


def _schedule_config(job):
    return {
        'enabled': job.get('enabled', False),
        'schedule': job.get('schedule', {}),
        'session_target': job.get('sessionTarget', ''),
        'wake_mode': job.get('wakeMode', ''),
    }


def _latest_run(job):
    state = job.get('state', {})
    latest = latest_run_entry(job['id'])
    recurring = latest_recurring_run_entry(job['id'], job.get('name'))
    latest_run = {
        'source': 'jobs_state',
        'run_status': state.get('lastRunStatus', ''),
        'delivered': bool(state.get('lastDelivered', False)),
        'delivery_status': state.get('lastDeliveryStatus', ''),
        'error': state.get('lastError') or state.get('lastDeliveryError') or '',
        'run_at_ms': state.get('lastRunAtMs'),
        'finished_at_ms': state.get('lastRunAtMs'),
        'summary': '',
    }

    if latest:
        latest_run.update({
            'source': 'run_log',
            'run_status': latest.get('status', latest_run['run_status']),
            'delivered': bool(latest.get('delivered', latest_run['delivered'])),
            'delivery_status': latest.get('deliveryStatus', latest_run['delivery_status']),
            'error': latest.get('error') or latest.get('deliveryError') or latest_run['error'],
            'run_at_ms': latest.get('runAtMs') or latest_run['run_at_ms'],
            'finished_at_ms': latest.get('ts') or latest_run['finished_at_ms'],
            'summary': latest.get('summary', ''),
        })

    if recurring:
        recurring_finished_at_ms = int(recurring.get('completed_at') or recurring.get('started_at') or 0) * 1000
        latest_finished_at_ms = int(latest_run.get('finished_at_ms') or 0)
        if recurring_finished_at_ms >= latest_finished_at_ms:
            delivered = False
            delivery_status = ''
            summary = recurring.get('stdout_summary') or ''
            error = recurring.get('last_error') or recurring.get('stderr_summary') or ''
            try:
                parsed = json.loads(summary) if summary else {}
            except json.JSONDecodeError:
                parsed = {}
            result = parsed.get('result') if isinstance(parsed, dict) else {}
            channel_delivery = result.get('channel_delivery') if isinstance(result, dict) else {}
            if isinstance(channel_delivery, dict):
                delivery_id = str(channel_delivery.get('delivery_id') or '')
                delivery_status = str(channel_delivery.get('status') or '')
                delivered = delivery_status == 'delivered'
                if not error:
                    error = str(channel_delivery.get('status_detail') or '')
                if delivery_id and not delivery_status:
                    delivery_record = load_delivery_record(delivery_id)
                    if delivery_record:
                        delivery_status = str(delivery_record.get('status') or '')
                        delivered = delivery_status == 'delivered'
                        if not error:
                            error = str(delivery_record.get('status_detail') or '')
            if not delivery_status:
                match = re.search(r'"delivery_id"\s*:\s*"([^"]+)"', summary)
                delivery_record = load_delivery_record(match.group(1) if match else '')
                if delivery_record:
                    delivery_status = str(delivery_record.get('status') or '')
                    delivered = delivery_status == 'delivered'
                    if not error:
                        error = str(delivery_record.get('status_detail') or '')
            latest_run.update({
                'source': 'loom_recurring',
                'run_status': 'ok' if recurring.get('status') == 'completed' and int(recurring.get('exit_code') or 0) == 0 else 'error',
                'delivered': delivered,
                'delivery_status': delivery_status,
                'error': error,
                'run_at_ms': int(recurring.get('started_at') or 0) * 1000,
                'finished_at_ms': recurring_finished_at_ms,
                'summary': summary,
            })

    latest_run['raw_delivered'] = latest_run['delivered']
    latest_run['raw_delivery_status'] = latest_run['delivery_status']
    latest_run['delivery_truth_note'] = ''
    summary = (latest_run.get('summary') or '').lower()
    blocked_summary = any(
        marker in summary
        for marker in (
            'blocked by constitutional preflight',
            'no brief',
            'cannot be treated as ready for delivery',
        )
    )
    if latest_run['run_status'] != 'ok' or latest_run['error'] or blocked_summary:
        latest_run['delivered'] = False
        latest_run['delivery_status'] = 'blocked'
        if latest_run['raw_delivered']:
            latest_run['delivery_truth_note'] = 'Raw run log marked delivered, but summary/error shows no real delivery.'

    latest_run['run_at'] = _fmt_ms(latest_run['run_at_ms'])
    latest_run['finished_at'] = _fmt_ms(latest_run['finished_at_ms'])
    latest_run['error_code'] = _error_code(latest_run['error'])
    return latest_run


def _contradictions(job, latest_run):
    state = job.get('state', {})
    contradictions = []
    if latest_run['source'] == 'run_log':
        if state.get('lastRunStatus') and state.get('lastRunStatus') != latest_run['run_status']:
            contradictions.append(
                f"jobs.json lastRunStatus={state.get('lastRunStatus')} but run log status={latest_run['run_status']}"
            )
        if state.get('lastDelivered') is not None and bool(state.get('lastDelivered')) != latest_run['delivered']:
            contradictions.append(
                f"jobs.json lastDelivered={bool(state.get('lastDelivered'))} but run log delivered={latest_run['delivered']}"
            )
        if latest_run.get('delivery_truth_note'):
            contradictions.append(latest_run['delivery_truth_note'])
        state_error = state.get('lastError') or state.get('lastDeliveryError') or ''
        if state_error and state_error != latest_run['error']:
            contradictions.append('jobs.json last error differs from latest run log error')
    return contradictions


def job_view(job, runtime_truth=None):
    runtime_truth = dict(runtime_truth or {})
    runtime_ok = bool(runtime_truth.get('loom_health_ok'))
    latest_run = _latest_run(job)
    note = ''
    if latest_run['error_code'] == 'deactivated_workspace' and runtime_ok:
        note = 'historical deactivated_workspace failure; current host runtime is healthy'
    return {
        'id': job['id'],
        'name': job.get('name', job['id']),
        'schedule_config': _schedule_config(job),
        'latest_run': latest_run,
        'current_runtime': runtime_truth,
        'contradictions': _contradictions(job, latest_run),
        'note': note,
    }


def all_job_truth():
    runtime_truth = _runtime_truth()
    return {
        'current_runtime': runtime_truth,
        'jobs': [job_view(job, runtime_truth=runtime_truth) for job in load_jobs()],
    }


def job_truth(job_name_or_id, runtime_truth=None):
    runtime_truth = _runtime_truth() if runtime_truth is None else runtime_truth
    for job in load_jobs():
        if job['id'] == job_name_or_id or job.get('name') == job_name_or_id:
            return job_view(job, runtime_truth=runtime_truth)
    return None


def _print_table(rows, runtime_truth):
    runtime_label = 'healthy' if runtime_truth.get('loom_health_ok') else 'unhealthy'
    print(
        'Current runtime: '
        f"{runtime_label} "
        f"(doctor_ok={runtime_truth.get('doctor_ok')} "
        f"critical={runtime_truth.get('critical_count', 0)} "
        f"warn={runtime_truth.get('warn_count', 0)})"
    )
    print(f"{'Job':<22} {'Run':<8} {'Delivery':<12} {'Source':<8} {'Finished'}")
    print(f"{'-'*22} {'-'*8} {'-'*12} {'-'*8} {'-'*20}")
    for row in rows:
        latest_run = row['latest_run']
        print(
            f"{row['name']:<22} {latest_run['run_status'] or '-':<8} "
            f"{latest_run['delivery_status'] or '-':<12} {latest_run['source']:<8} {latest_run['finished_at'] or '-'}"
        )
        if row.get('note'):
            print(f"  · {row['note']}")
        for contradiction in row['contradictions']:
            print(f"  ! {contradiction}")


def main():
    parser = argparse.ArgumentParser(description='Canonical scheduler truth from Meridian run logs')
    parser.add_argument('--job', help='Job name or id')
    parser.add_argument('--json', action='store_true', help='Output JSON')
    args = parser.parse_args()

    if args.job:
        runtime_truth = _runtime_truth()
        data = job_truth(args.job, runtime_truth=runtime_truth)
        if data is None:
            raise SystemExit(f'Unknown job: {args.job}')
    else:
        data = all_job_truth()

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        if isinstance(data, dict) and 'jobs' in data:
            _print_table(data['jobs'], data['current_runtime'])
        else:
            _print_table([data], data['current_runtime'])


if __name__ == '__main__':
    main()
