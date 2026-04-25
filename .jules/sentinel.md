## 2024-04-25 - Subprocess Timeout Vulnerability
**Vulnerability:** Missing timeout configurations on external subprocess calls.
**Learning:** Found an unbounded `subprocess.run` call executing `SKILL_VALIDATOR` that could lead to DoS if the external command hangs.
**Prevention:** Always specify a `timeout` when using `subprocess.run` with external or potentially unbounded commands, and handle `subprocess.TimeoutExpired` gracefully.
