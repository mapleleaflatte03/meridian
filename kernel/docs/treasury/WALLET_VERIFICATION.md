# Wallet Verification

Wallet classification system for the Meridian treasury protocol.

---

## 1. Verification Levels

| Level | Label | Description | Payout Eligible |
|-------|-------|-------------|-----------------|
| 0 | `observed_only` | Address seen on-chain. No ownership claim. | NO |
| 1 | `linked` | Owner claims ownership. No cryptographic proof. | NO |
| 2 | `exchange_linked` | Exchange deposit screen observed. NOT self-custody. | NO |
| 3 | `self_custody_verified` | SIWE signature proving key control. | YES |
| 4 | `multisig_controlled` | Gnosis Safe or similar with defined signers. | YES |

Only Level 3 and Level 4 wallets may receive payouts. This is enforced by `can_receive_payout()` in `kernel/treasury.py`.

---

## 2. Current Wallet Inventory

| Wallet ID | Address | Level | Label | Payout Eligible | Status |
|-----------|---------|-------|-------|-----------------|--------|
| `company_treasury_v1` | `0x8200...7761` | 1 | linked | NO | active |
| `founder_exchange_linked` | `0x66e9...e078` | 2 | exchange_linked | NO | active |
| `observed_sender_17fe` | `0x17fe...645a` | 0 | observed_only | NO | observed |
| `company_treasury_multisig_target` | (not deployed) | -- | -- | NO | planned |

**Current payout-eligible wallets: 0**

No payouts can be executed until at least one Level 3+ wallet is registered.

---

## 3. SIWE Verification (Level 3) -- Planned

Sign-In with Ethereum (SIWE) provides cryptographic proof that a person controls a wallet's private key.

**Target design:**
1. Wallet owner generates a SIWE challenge message
2. Owner signs the message with their wallet's private key
3. System verifies the signature matches the claimed address
4. Wallet is upgraded to Level 3

**Implementation status:** Not implemented. Target for v0.2 or when first payout-eligible wallet is needed.

**Requirements for implementation:**
- EIP-4361 compliant message format
- Signature verification (can use `eth_account` library or pure Python implementation)
- Challenge must include nonce and expiry to prevent replay
- Verification record stored with timestamp and signature hash

---

## 4. Safe Multisig (Level 4) -- Planned

Gnosis Safe provides shared custody with configurable signer thresholds.

**Target design:**
- Chain: Base (same as existing wallets)
- Threshold: 2-of-3 signers minimum
- Signers: Owner + trusted maintainer(s)
- Used for: Company treasury upgrades, high-value payouts

**Implementation status:** Not deployed. Requires at least 2 trusted signers.

**Requirements for deployment:**
- Deploy Safe contract on Base
- Configure signer addresses (all must be Level 3 verified first)
- Register Safe address in `wallets.json` as Level 4
- Test with a small transfer before routing treasury funds

---

## 5. Why Exchange-Linked Wallets Cannot Receive Payouts

Exchange wallets (Level 2) are controlled by the exchange, not the user. Risks:

1. **No key control** -- the exchange holds the private key, not the claimed owner
2. **Account freeze** -- exchanges can freeze accounts and seize funds
3. **KYC mismatch** -- the exchange account may not match the contributor's identity
4. **No recovery** -- if the exchange blocks the account, the payout is lost

Contributors must provide a self-custody wallet (Level 3) for payouts. Hardware wallets, software wallets, and multisigs are all acceptable.

---

## 6. Wallet Registration Process

To register a new wallet:

1. Add entry to `treasury/wallets.json` with Level 0 (observed_only)
2. Claim ownership -- upgrade to Level 1 (linked) with owner attestation
3. Verify custody -- upgrade to Level 3 via SIWE signature (when implemented)
4. For multisig -- deploy Safe and register as Level 4

Each upgrade is recorded with timestamp and verification details.
