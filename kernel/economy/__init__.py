"""
Meridian Economy -- Three-ledger scoring, sanctions, authority, and revenue.

Implements the three non-interchangeable ledgers:

  * REP  (reputation_units) -- long-term trust
  * AUTH (authority_units)  -- temporary power / sprint-lead eligibility
  * CASH (treasury_cash)    -- real company money

Modules:
  * score      -- REP/AUTH scoring tool
  * authority  -- AUTH-based action rights and sprint-lead selection
  * sanctions  -- Sanction enforcement (apply, lift, auto-check)
  * auto_score -- Automated epoch scoring from pipeline artifacts
  * revenue    -- Client/order state machine and treasury credits
"""
