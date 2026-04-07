# Contributing to Meridian Constitutional Kernel

Thank you for considering a contribution to the Meridian Constitutional Kernel. This project builds the foundational primitives for governed digital labor, and every contribution matters.

## Quick Start

```bash
git clone https://github.com/mapleleaflatte03/meridian-kernel.git
cd meridian-kernel
python3 economy/tests/test_economy.py
python3 quickstart.py --init-only
```

The kernel requires **Python 3.9+** and uses only the standard library. There are no external dependencies to install.
The built-in local demo path is the supported contributor entrypoint today; external runtime adapters are still partial or planned.

## Development Setup

1. **Fork and clone** the repository.
2. **Create a branch** from `main` for your work.
3. **Run the test suite** before making changes to confirm a clean baseline:
   ```bash
   python3 economy/tests/test_economy.py
   ```
4. **Run the quickstart demo** to see the five primitives in action:
   ```bash
   python3 quickstart.py --init-only
   python3 kernel/phase_machine.py status
   ```

## Code Style

- **Python 3.9+**, standard library only. No external dependencies.
- Follow [PEP 8](https://peps.python.org/pep-0008/) for formatting.
- Use type hints for all public function signatures.
- Prefer explicit over clever. The kernel is a governance layer; readability is a safety property.
- Keep modules focused on a single primitive: `institution.py`, `agent.py`, `authority.py`, `treasury.py`, `court.py`.
- No `requirements.txt` for the core kernel. If your change requires a third-party package, it belongs in a plugin or extension, not the kernel.

## Submitting Issues

- **Bugs**: Use the Bug Report issue template. Include steps to reproduce, expected behavior, and your Python version.
- **Feature requests**: Use the Feature Request template. Describe the use case before the solution.
- **Questions**: Use [GitHub Discussions](https://github.com/mapleleaflatte03/meridian-kernel/discussions), not issues.
- **Security vulnerabilities**: Do **not** open a public issue. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## Submitting Pull Requests

1. Open an issue first for non-trivial changes so the approach can be discussed before you invest time.
2. Keep PRs focused. One logical change per PR.
3. Add or update tests for any behavioral change.
4. Ensure the verified local checks pass with no failures:
   ```bash
   python3 economy/tests/test_economy.py
   python3 quickstart.py --init-only
   ```
5. Fill out the pull request template completely.

### Commit Message Convention

Use the following format:

```
<type>: <short summary>

<optional body explaining why, not what>
```

Types:
- `feat` — new functionality
- `fix` — bug fix
- `refactor` — code restructuring without behavior change
- `test` — adding or updating tests
- `docs` — documentation changes
- `chore` — maintenance tasks (CI, build, tooling)

Examples:
```
feat: add budget enforcement to Treasury primitive
fix: prevent negative authority delegation depth
docs: clarify Court appeal escalation flow
test: add edge cases for Institution charter validation
```

Keep the summary line under 72 characters. Use the body for context on *why* the change is necessary.

## Good First Issues

Look for issues labeled [`good first issue`](https://github.com/mapleleaflatte03/meridian-kernel/labels/good%20first%20issue). These are scoped to be approachable for newcomers and typically involve:

- Adding test coverage for existing primitives
- Improving docstrings or inline documentation
- Small behavioral fixes with clear reproduction steps
- Adding example verticals that demonstrate kernel usage

If you want to work on one, leave a comment on the issue so others know it is claimed.

## Licensing

This project uses the [Apache License 2.0](LICENSE). Contributions are accepted under the same license with no additional contributor license agreement (CLA) required. By submitting a pull request, you agree that your contribution is licensed under Apache-2.0 (inbound = outbound).

## Code of Conduct

All participants in this project are expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Please report unacceptable behavior to nguyensimon186@gmail.com.
