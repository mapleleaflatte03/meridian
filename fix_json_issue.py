# If ALLOW_API_SKIP is checked, we exit correctly.
# BUT wait! Does my code actually WORK?
# In CI, the error says:
#   File "<stdin>", line 107, in <module>
#   ... json.loads ... json.decoder.JSONDecodeError ...
# Wait. If ALLOW_API_SKIP is True, it would just print `[SKIP]...` and `sys.exit(0)`.
# But in CI, it DID NOT PRINT `[SKIP] MERIDIAN_ALLOW_API_SKIP=1 - skipping network checks in CI`.
# It executed the tests!
# Let's check the CI log again:
# test_workspace_status_snapshot_repairs_cached_treasury_nulls ... ok
# ----------------------------------------------------------------------
# Ran 19 tests in 0.025s
# OK
# ....
# ----------------------------------------------------------------------
# Ran 4 tests in 0.034s
# OK
# Traceback (most recent call last):
#   File "<stdin>", line 107, in <module>
#   File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/json/__init__.py", line 346, in loads
#     return _default_decoder.decode(s)

# WAIT. `MERIDIAN_ALLOW_API_SKIP` IS NOT SET FOR `python-kernel-intelligence`!
# Let me look at `.github/workflows/ci.yml`.
