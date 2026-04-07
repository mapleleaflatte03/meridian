#!/usr/bin/env python3
"""Provision a segregated hot wallet and optionally prepare/sign a Base USDC x402 transfer."""
import argparse
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KERNEL_DIR = ROOT / 'kernel'
if str(KERNEL_DIR) not in sys.path:
    sys.path.insert(0, str(KERNEL_DIR))

import treasury  # noqa: E402


def _write_secret_file(secret_path, payload):
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write('\n')
    except Exception:
        try:
            os.unlink(secret_path)
        except OSError:
            pass
        raise
    os.chmod(secret_path, 0o600)


def provision_hot_wallet(*, org_id=None, wallet_id='automated_loom_settlement_v1',
                         account_id='automated_loom_settlement',
                         actor_id='ops:provision_hot_wallet', secret_dir='.hot-wallet-secrets',
                         wallet_label='Automated Loom Settlement Hot Wallet',
                         account_label='Automated Loom Settlement',
                         account_purpose='Legally segregated automated settlement hot wallet for Loom and x402 execution.',
                         reserve_floor_usd=0.0):
    if treasury.get_wallet(wallet_id, org_id):
        raise ValueError(f'Wallet already exists: {wallet_id}')
    if treasury.get_treasury_account(account_id, org_id):
        raise ValueError(f'Treasury account already exists: {account_id}')

    Account = treasury._load_eth_account_backend()
    generated = Account.create()
    private_key_hex = '0x' + generated.key.hex()
    address = generated.address.lower()

    secret_root = Path(secret_dir)
    if not secret_root.is_absolute():
        secret_root = ROOT / secret_root
    secret_path = secret_root / f'{wallet_id}.json'
    if secret_path.exists():
        raise ValueError(f'Secret file already exists: {secret_path}')

    wallet = treasury.register_wallet(
        wallet_id,
        address,
        actor_id=actor_id,
        org_id=org_id,
        label=wallet_label,
        chain='base',
        asset='USDC',
        verification_level=3,
        verification_label='self_custody_verified',
        verification_details=(
            'Private key generated in-process by ops_provision_hot_wallet.py and written '
            'to an operator-controlled secret path on this host.'
        ),
        payout_eligible=True,
        status='active',
        notes='Segregated automated hot wallet. Do not commingle with founder treasury sources.',
    )
    account = treasury.register_treasury_account(
        account_id,
        wallet_id=wallet_id,
        actor_id=actor_id,
        org_id=org_id,
        label=account_label,
        purpose=account_purpose,
        balance_usd=0.0,
        reserve_floor_usd=reserve_floor_usd,
        status='active',
        notes='Dedicated execution source for automated federation and x402 settlement flows.',
    )
    secret_payload = {
        'wallet_id': wallet_id,
        'account_id': account_id,
        'address': address,
        'private_key_hex': private_key_hex,
        'chain': 'base',
        'asset': 'USDC',
        'created_at': treasury._now(),
        'custody_assertion': 'Generated locally and stored only in the ignored secret path below.',
    }
    _write_secret_file(secret_path, secret_payload)
    mode = stat.S_IMODE(secret_path.stat().st_mode)
    return {
        'wallet': wallet,
        'account': account,
        'address': address,
        'secret_path': str(secret_path),
        'secret_file_mode': oct(mode),
        'private_key_hex': private_key_hex,
    }


def _build_parser():
    parser = argparse.ArgumentParser(description='Provision a segregated hot wallet and optional x402 signing artifact.')
    parser.add_argument('--org_id', default=None)
    parser.add_argument('--wallet_id', default='automated_loom_settlement_v1')
    parser.add_argument('--account_id', default='automated_loom_settlement')
    parser.add_argument('--actor_id', default='ops:provision_hot_wallet')
    parser.add_argument('--secret_dir', default='.hot-wallet-secrets')
    parser.add_argument('--wallet_label', default='Automated Loom Settlement Hot Wallet')
    parser.add_argument('--account_label', default='Automated Loom Settlement')
    parser.add_argument('--account_purpose', default='Legally segregated automated settlement hot wallet for Loom and x402 execution.')
    parser.add_argument('--reserve_floor_usd', type=float, default=0.0)
    parser.add_argument('--recipient_address', default='')
    parser.add_argument('--amount_usdc', default='')
    parser.add_argument('--token_contract_address', default='')
    parser.add_argument('--rpc_url', default='')
    parser.add_argument('--private_key_env', default='MERIDIAN_X402_DEV_PRIVATE_KEY')
    parser.add_argument('--nonce', default='')
    parser.add_argument('--gas_limit', default='')
    parser.add_argument('--gas_price_wei', default='')
    parser.add_argument('--chain_id', default='')
    parser.add_argument('--token_decimals', type=int, default=6)
    parser.add_argument('--timeout_seconds', type=int, default=10)
    parser.add_argument('--host_supported_adapter', action='append', default=[])
    parser.add_argument('--allow_mainnet_signing', action='store_true')
    parser.add_argument('--broadcast', action='store_true')
    parser.add_argument('--allow_mainnet_broadcast', action='store_true')
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    provisioned = provision_hot_wallet(
        org_id=args.org_id,
        wallet_id=args.wallet_id,
        account_id=args.account_id,
        actor_id=args.actor_id,
        secret_dir=args.secret_dir,
        wallet_label=args.wallet_label,
        account_label=args.account_label,
        account_purpose=args.account_purpose,
        reserve_floor_usd=args.reserve_floor_usd,
    )
    output = {
        'wallet': provisioned['wallet'],
        'account': provisioned['account'],
        'address': provisioned['address'],
        'secret_path': provisioned['secret_path'],
        'secret_file_mode': provisioned['secret_file_mode'],
    }
    if args.recipient_address or args.amount_usdc or args.token_contract_address:
        missing = [
            name for name, value in (
                ('recipient_address', args.recipient_address),
                ('amount_usdc', args.amount_usdc),
                ('token_contract_address', args.token_contract_address),
            ) if not str(value or '').strip()
        ]
        if missing:
            raise SystemExit(f'Missing required x402 signing arguments: {", ".join(missing)}')
        signing = treasury.sign_x402_transfer_from_wallet(
            args.actor_id,
            org_id=args.org_id,
            rpc_url=args.rpc_url,
            token_contract_address=args.token_contract_address,
            recipient_address=args.recipient_address,
            amount_usdc=args.amount_usdc,
            private_key_env=args.private_key_env,
            private_key=provisioned['private_key_hex'],
            source_account_id=args.account_id,
            nonce=args.nonce or None,
            gas_limit=args.gas_limit or None,
            gas_price_wei=args.gas_price_wei or None,
            chain_id=args.chain_id or None,
            token_decimals=args.token_decimals,
            host_supported_adapters=args.host_supported_adapter or None,
            timeout_seconds=args.timeout_seconds,
            allow_mainnet_signing=args.allow_mainnet_signing,
            broadcast=args.broadcast,
            allow_mainnet_broadcast=args.allow_mainnet_broadcast,
        )
        output['x402_signing'] = signing
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
