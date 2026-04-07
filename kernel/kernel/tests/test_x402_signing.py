#!/usr/bin/env python3
import contextlib
import importlib.util
import json
import pathlib
import shutil
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
TREASURY_PATH = ROOT / 'kernel' / 'treasury.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from eth_account import Account
    HAS_ETH_ACCOUNT = True
except Exception:
    Account = None
    HAS_ETH_ACCOUNT = False


treasury = _load_module('kernel_treasury_x402_signing_test', TREASURY_PATH)
capsule = _load_module('kernel_capsule_x402_signing_test', CAPSULE_PATH)


def _rpc_uint256(value):
    return '0x' + format(int(value), '064x')


@contextlib.contextmanager
def _json_rpc_server(resolver):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            calls.append(payload)
            response = {
                'jsonrpc': '2.0',
                'id': payload.get('id'),
            }
            try:
                response['result'] = resolver(payload)
            except Exception as exc:
                response['error'] = {
                    'code': -32000,
                    'message': str(exc),
                }
            body = json.dumps(response).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}', calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@unittest.skipUnless(HAS_ETH_ACCOUNT, 'eth_account not available')
class X402SigningTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_x402_signing_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

        ledger_path = self.capsule_dir / 'ledger.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['updatedAt'] = '2026-03-26T00:00:00Z'
        ledger['epoch']['started_at'] = '2026-03-26T00:00:00Z'
        ledger['treasury']['cash_usd'] = 120.0
        ledger['treasury']['reserve_floor_usd'] = 50.0
        ledger['treasury']['expenses_recorded_usd'] = 0.0
        ledger_path.write_text(json.dumps(ledger, indent=2))

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def _stage_x402_proposal(self, *, sender_address, recipient_address, sender_level=4,
                             sender_label='multisig_controlled', amount_usd=2.0):
        (self.capsule_dir / 'wallets.json').write_text(json.dumps({
            'wallets': {
                'wallet_source': {
                    'id': 'wallet_source',
                    'address': sender_address,
                    'chain': 'base',
                    'asset': 'USDC',
                    'verification_level': sender_level,
                    'verification_label': sender_label,
                    'payout_eligible': True,
                    'status': 'active',
                },
                'wallet_exec': {
                    'id': 'wallet_exec',
                    'address': recipient_address,
                    'chain': 'base',
                    'asset': 'USDC',
                    'verification_level': 3,
                    'verification_label': 'self_custody_verified',
                    'payout_eligible': True,
                    'status': 'active',
                },
            },
            'verification_levels': {},
        }, indent=2))
        (self.capsule_dir / 'treasury_accounts.json').write_text(json.dumps({
            'accounts': {
                'company_treasury': {
                    'id': 'company_treasury',
                    'wallet_id': 'wallet_source',
                    'balance_usd': 120.0,
                    'reserve_floor_usd': 50.0,
                    'status': 'active',
                }
            },
            'transfer_policy': {},
        }, indent=2))
        (self.capsule_dir / 'contributors.json').write_text(json.dumps({
            'contributors': {
                'contrib_exec': {
                    'id': 'contrib_exec',
                    'name': 'Contributor Exec',
                    'payout_wallet_id': 'wallet_exec',
                }
            },
            'contribution_types': ['code'],
            'registration_requirements': {},
        }, indent=2))
        (self.capsule_dir / 'settlement_adapters.json').write_text(json.dumps({
            'default_payout_adapter': 'base_usdc_x402',
            'adapters': {
                'base_usdc_x402': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                    'verification_ready': True,
                },
            },
        }, indent=2))

        proposal = treasury.create_payout_proposal(
            'contrib_exec',
            amount_usd,
            'code',
            proposed_by='user:proposer',
            org_id=self.org_id,
            evidence={'description': 'x402 signing test'},
            settlement_adapter='base_usdc_x402',
        )
        proposal = treasury.submit_payout_proposal(
            proposal['proposal_id'],
            'user:proposer',
            org_id=self.org_id,
        )
        proposal = treasury.review_payout_proposal(
            proposal['proposal_id'],
            'user:reviewer',
            org_id=self.org_id,
        )
        proposal = treasury.approve_payout_proposal(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
        )
        return treasury.open_payout_dispute_window(
            proposal['proposal_id'],
            'user:owner',
            org_id=self.org_id,
            dispute_window_hours=0,
        )

    def test_sign_x402_transfer_generates_signed_raw_hex_for_dev_chain(self):
        private_key = '0x59c6995e998f97a5a0044966f09453870d6ea5d61ff6d1bc1b3b76b5f3c4f8f7'
        sender_address = Account.from_key(private_key).address
        recipient_address = '0x2222222222222222222222222222222222222222'
        token_contract = '0x3333333333333333333333333333333333333333'
        proposal = self._stage_x402_proposal(
            sender_address=sender_address,
            recipient_address=recipient_address,
        )

        def resolver(payload):
            method = payload['method']
            params = payload.get('params', [])
            if method == 'eth_chainId':
                return hex(1337)
            if method == 'eth_getTransactionCount':
                self.assertEqual(params, [sender_address.lower(), 'pending'])
                return hex(3)
            if method == 'eth_gasPrice':
                return hex(1_500_000_000)
            if method == 'eth_estimateGas':
                tx = params[0]
                self.assertEqual(tx['from'], sender_address.lower())
                self.assertEqual(tx['to'], token_contract.lower())
                self.assertEqual(tx['value'], '0x0')
                self.assertTrue(tx['data'].startswith('0x' + treasury._ERC20_TRANSFER_SELECTOR))
                return hex(65000)
            if method == 'eth_getBalance':
                return hex(10 ** 18)
            if method == 'eth_call':
                call = params[0]
                data = call['data']
                if data == '0x' + treasury._ERC20_DECIMALS_SELECTOR:
                    return _rpc_uint256(6)
                if data == treasury._encode_erc20_balance_of_calldata(sender_address.lower()):
                    return _rpc_uint256(5_000_000)
                if data == treasury._encode_erc20_balance_of_calldata(recipient_address.lower()):
                    return _rpc_uint256(0)
            raise AssertionError(f'unexpected rpc payload: {payload}')

        with _json_rpc_server(resolver) as (rpc_url, rpc_calls),              mock.patch.object(treasury, '_current_phase', lambda org_id=None: (5, {'name': 'Contributor Payouts'})),              mock.patch.dict('os.environ', {'MERIDIAN_X402_DEV_PRIVATE_KEY': private_key}, clear=False):
            result = treasury.sign_x402_transfer_for_payout(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                rpc_url=rpc_url,
                token_contract_address=token_contract,
                host_supported_adapters=['base_usdc_x402'],
            )

        self.assertTrue(result['unsigned_transaction_prepared'])
        self.assertTrue(result['signing_performed'])
        self.assertIsNotNone(result['signed_transaction'])
        self.assertFalse(result['broadcast']['attempted'])
        self.assertEqual(result['token']['network_classification'], 'dev_or_nonmainnet')
        self.assertEqual(result['amount']['base_units'], '2000000')
        self.assertEqual(result['signing_blockers'], [])
        self.assertTrue(result['signed_transaction']['raw_transaction_hex'].startswith('0x'))
        self.assertTrue(result['signed_transaction']['signed_tx_hash'].startswith('0x'))
        self.assertEqual(result['signed_transaction']['sender_address'], sender_address.lower())
        self.assertEqual(len(rpc_calls), 8)
        self.assertIn('signed raw transaction for a non-mainnet path', result['truth_boundary'])

    def test_sign_x402_transfer_blocks_base_mainnet_signing_by_default(self):
        private_key = '0x8b3a350cf5c34c9194ca7b8264f7f3f8dc5c6c6e5e7a5f6f8421d5c1f9d0c1ab'
        sender_address = Account.from_key(private_key).address
        recipient_address = '0x4444444444444444444444444444444444444444'
        token_contract = '0x5555555555555555555555555555555555555555'
        proposal = self._stage_x402_proposal(
            sender_address=sender_address,
            recipient_address=recipient_address,
        )

        def resolver(payload):
            method = payload['method']
            if method == 'eth_chainId':
                return hex(8453)
            if method == 'eth_getTransactionCount':
                return hex(1)
            if method == 'eth_gasPrice':
                return hex(1_000_000_000)
            if method == 'eth_estimateGas':
                return hex(65000)
            if method == 'eth_getBalance':
                return hex(10 ** 18)
            if method == 'eth_call':
                data = payload['params'][0]['data']
                if data == '0x' + treasury._ERC20_DECIMALS_SELECTOR:
                    return _rpc_uint256(6)
                return _rpc_uint256(5_000_000)
            raise AssertionError(f'unexpected rpc payload: {payload}')

        with _json_rpc_server(resolver) as (rpc_url, _rpc_calls),              mock.patch.object(treasury, '_current_phase', lambda org_id=None: (5, {'name': 'Contributor Payouts'})),              mock.patch.dict('os.environ', {'MERIDIAN_X402_DEV_PRIVATE_KEY': private_key}, clear=False):
            result = treasury.sign_x402_transfer_for_payout(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                rpc_url=rpc_url,
                token_contract_address=token_contract,
                host_supported_adapters=['base_usdc_x402'],
            )

        self.assertFalse(result['signing_performed'])
        blocker_codes = {item['code'] for item in result['signing_blockers']}
        self.assertIn('mainnet_signing_disabled', blocker_codes)
        self.assertIsNone(result['signed_transaction'])
        self.assertIn('No Base mainnet transfer or tx hash was executed', result['truth_boundary'])

    def test_sign_x402_transfer_can_broadcast_to_local_dev_rpc(self):
        private_key = '0x59c6995e998f97a5a0044966f09453870d6ea5d61ff6d1bc1b3b76b5f3c4f8f7'
        sender_address = Account.from_key(private_key).address
        recipient_address = '0x6666666666666666666666666666666666666666'
        token_contract = '0x7777777777777777777777777777777777777777'
        proposal = self._stage_x402_proposal(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount_usd=1.5,
        )
        submitted_raw = []
        rpc_tx_hash = '0x' + 'ab' * 32

        def resolver(payload):
            method = payload['method']
            params = payload.get('params', [])
            if method == 'eth_chainId':
                return hex(1337)
            if method == 'eth_getTransactionCount':
                return hex(0)
            if method == 'eth_gasPrice':
                return hex(2_000_000_000)
            if method == 'eth_estimateGas':
                return hex(65000)
            if method == 'eth_getBalance':
                return hex(10 ** 18)
            if method == 'eth_call':
                data = params[0]['data']
                if data == '0x' + treasury._ERC20_DECIMALS_SELECTOR:
                    return _rpc_uint256(6)
                return _rpc_uint256(10_000_000)
            if method == 'eth_sendRawTransaction':
                submitted_raw.append(params[0])
                return rpc_tx_hash
            raise AssertionError(f'unexpected rpc payload: {payload}')

        with _json_rpc_server(resolver) as (rpc_url, rpc_calls),              mock.patch.object(treasury, '_current_phase', lambda org_id=None: (5, {'name': 'Contributor Payouts'})),              mock.patch.dict('os.environ', {'MERIDIAN_X402_DEV_PRIVATE_KEY': private_key}, clear=False):
            result = treasury.sign_x402_transfer_for_payout(
                proposal['proposal_id'],
                'user:owner',
                org_id=self.org_id,
                rpc_url=rpc_url,
                token_contract_address=token_contract,
                host_supported_adapters=['base_usdc_x402'],
                broadcast=True,
            )

        self.assertTrue(result['signing_performed'])
        self.assertTrue(result['broadcast']['attempted'])
        self.assertTrue(result['broadcast']['allowed'])
        self.assertEqual(result['broadcast']['rpc_tx_hash'], rpc_tx_hash)
        self.assertEqual(submitted_raw, [result['signed_transaction']['raw_transaction_hex']])
        self.assertEqual(rpc_calls[-1]['method'], 'eth_sendRawTransaction')
        self.assertIn('non-mainnet or local RPC endpoint', result['truth_boundary'])


if __name__ == '__main__':
    unittest.main()
