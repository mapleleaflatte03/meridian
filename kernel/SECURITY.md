# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.x     | Yes       |

This project is pre-1.0. All releases in the 0.x series receive security
fixes.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, report vulnerabilities by email to: **nguyensimon186@gmail.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

### Response Timeline

| Stage | Target |
|-------|--------|
| Acknowledgment | 48 hours |
| Initial assessment | 7 days |
| Fix development | 30 days (severity-dependent) |
| Public disclosure | After fix is released |

### What to Expect

1. You will receive an acknowledgment within 48 hours confirming receipt.
2. We will assess severity and inform you of our plan within 7 days.
3. We will work on a fix and coordinate disclosure timing with you.
4. You will be credited in the security advisory (unless you prefer anonymity).

### Safe Harbor

We consider security research conducted in good faith to be authorized.
We will not pursue legal action against researchers who:

- Act in good faith and within this policy
- Avoid privacy violations, data destruction, and service disruption
- Report findings promptly and allow reasonable time for remediation

## Security Design

Meridian's kernel is designed with these security principles:

- **No external dependencies** — pure Python stdlib reduces supply chain risk
- **File-based state** — no database attack surface
- **Audit trail** — append-only JSONL logging for all significant actions
- **Kill switch** — global emergency halt for all agent operations
- **Least privilege** — agents operate within scoped permissions and budgets

## OpenSSF

This project aims to meet OpenSSF Best Practices criteria. Current status
is tracked in the README.
