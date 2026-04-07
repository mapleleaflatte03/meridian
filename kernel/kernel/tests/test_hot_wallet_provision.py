#!/usr/bin/env python3
import contextlib
import importlib.util
import json
import pathlib
import shutil
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = pathlib.Path(__file__).resolve().parents[2]
TREASURY_PATH = ROOT / 'kernel' / 'treasury.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
OPS_PATH = ROOT / 'ops_provision_hot_wallet.py'
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


treasury = _load_module('kernel_treasury_hot_wallet_test', TREASURY_PATH)
capsule = _load_module('kernel_capsule_hot_wallet_test', CAPSULE_PATH)
ops = _load_module('kernel_ops_hot_wallet_test', OPS_PATH)


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
class HotWalletProvisionTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_hot_wallet_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)
        self.secret_dir = tempfile.mkdtemp(prefix='meridian-hot-wallet-')
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

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)
        shutil.rmtree(self.secret_dir, ignore_errors=True)

    def _register_hot_wallet(self, private_key):
        sender_address = Account.from_key(private_key).address
        treasury.register_wallet(
            'automated_loom_settlement_v1',
            sender_address,
            actor_id='ops:test',
            org_id=self.org_id,
            label='Automated Loom Settlement Hot Wallet',
            chain='base',
            asset='USDC',
            verification_level=3,
            verification_label='self_custody_verified',
            verification_details='generated in test',
            payout_eligible=True,
            status='active',
            notes='test wallet',
        )
        treasury.register_treasury_account(
            'automated_loom_settlement',
            wallet_id='automated_loom_settlement_v1',
            actor_id='ops:test',
            org_id=self.org_id,
            label='Automated Loom Settlement',
            purpose='test execution source',
            balance_usd=0.0,
            reserve_floor_usd=0.0,
            status='active',
            notes='test account',
        )
        return sender_address.lower()

    def test_provision_hot_wallet_registers_self_custody_wallet_and_account(self):
        result = ops.provision_hot_wallet(
            org_id=self.org_id,
            actor_id='ops:test',
            secret_dir=self.secret_dir,
        )

        wallet = treasury.get_wallet('automated_loom_settlement_v1', self.org_id)
        account = treasury.get_treasury_account('automated_loom_settlement', self.org_id)
        secret_path = pathlib.Path(result['secret_path'])
        secret_payload = json.loads(secret_path.read_text())

        self.assertEqual(result['address'], wallet['address'])
        self.assertEqual(wallet['verification_level'], 3)
        self.assertEqual(wallet['verification_label'], 'self_custody_verified')
        self.assertTrue(wallet['payout_eligible'])
        self.assertEqual(account['wallet_id'], 'automated_loom_settlement_v1')
        self.assertTrue(secret_path.exists())
        self.assertEqual(result['secret_file_mode'], '0o600')
        self.assertEqual(secret_payload['address'], result['address'])
        self.assertTrue(secret_payload['private_key_hex'].startswith('0x'))

    def test_sign_x402_transfer_from_wallet_generates_signed_raw_hex_offline(self):
        private_key = '0x59c6995e998f97a5a0044966f09453870d6ea5d61ff6d1bc1b3b76b5f3c4f8f7'
        sender_address = self._register_hot_wallet(private_key)
        token_contract = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'
        recipient_address = '0x9999999999999999999999999999999999999999'

        result = treasury.sign_x402_transfer_from_wallet(
            'ops:test',
            org_id=self.org_id,
            source_account_id='automated_loom_settlement',
            recipient_address=recipient_address,
            amount_usdc='1.25',
            token_contract_address=token_contract,
            private_key=private_key,
            chain_id=84532,
            nonce=0,
            gas_limit=65000,
            gas_price_wei=1_000_000_000,
            host_supported_adapters=['base_usdc_x402'],
        )

        blocker_codes = {item['code'] for item in result['actual_transfer_blockers']}
        self.assertTrue(result['unsigned_transaction_prepared'])
        self.assertTrue(result['signing_performed'])
        self.assertEqual(result['sender_wallet']['address'], sender_address)
        self.assertEqual(result['token']['network_classification'], 'base_sepolia')
        self.assertEqual(result['amount']['base_units'], '1250000')
        self.assertFalse(result['broadcast']['attempted'])
        self.assertEqual(result['signing_blockers'], [])
        self.assertTrue(result['signed_transaction']['raw_transaction_hex'].startswith('0x'))
        self.assertIn('live_chain_state_unverified', blocker_codes)
        self.assertIn('operator-supplied path', result['truth_boundary'])

    def test_sign_x402_transfer_from_wallet_can_broadcast_to_base_sepolia_rpc(self):
        private_key = '0x8b3a350cf5c34c9194ca7b8264f7f3f8dc5c6c6e5e7a5f6f8421d5c1f9d0c1ab'
        sender_address = self._register_hot_wallet(private_key)
        token_contract = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'
        recipient_address = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        submitted_raw = []
        rpc_tx_hash = '0x' + 'cd' * 32

        def resolver(payload):
            method = payload['method']
            params = payload.get('params', [])
            if method == 'eth_chainId':
                return hex(84532)
            if method == 'eth_getTransactionCount':
                self.assertEqual(params, [sender_address, 'pending'])
                return hex(0)
            if method == 'eth_gasPrice':
                return hex(2_000_000_000)
            if method == 'eth_estimateGas':
                tx = params[0]
                self.assertEqual(tx['from'], sender_address)
                self.assertEqual(tx['to'], token_contract.lower())
                self.assertEqual(tx['value'], '0x0')
                return hex(65000)
            if method == 'eth_getBalance':
                return hex(10 ** 18)
            if method == 'eth_call':
                data = params[0]['data']
                if data == '0x' + treasury._ERC20_DECIMALS_SELECTOR:
                    return _rpc_uint256(6)
                if data == treasury._encode_erc20_balance_of_calldata(sender_address):
                    return _rpc_uint256(3_000_000)
                if data == treasury._encode_erc20_balance_of_calldata(recipient_address.lower()):
                    return _rpc_uint256(0)
            if method == 'eth_sendRawTransaction':
                submitted_raw.append(params[0])
                return rpc_tx_hash
            raise AssertionError(f'unexpected rpc payload: {payload}')

        with _json_rpc_server(resolver) as (rpc_url, rpc_calls):
            result = treasury.sign_x402_transfer_from_wallet(
                'ops:test',
                org_id=self.org_id,
                rpc_url=rpc_url,
                source_account_id='automated_loom_settlement',
                recipient_address=recipient_address,
                amount_usdc='1',
                token_contract_address=token_contract,
                private_key=private_key,
                host_supported_adapters=['base_usdc_x402'],
                broadcast=True,
            )

        self.assertTrue(result['signing_performed'])
        self.assertEqual(result['token']['network_classification'], 'base_sepolia')
        self.assertTrue(result['broadcast']['attempted'])
        self.assertTrue(result['broadcast']['allowed'])
        self.assertEqual(result['broadcast']['rpc_tx_hash'], rpc_tx_hash)
        self.assertEqual(submitted_raw, [result['signed_transaction']['raw_transaction_hex']])
        self.assertEqual(rpc_calls[-1]['method'], 'eth_sendRawTransaction')
        self.assertIn('Base Sepolia or another non-mainnet/local RPC endpoint', result['truth_boundary'])


if __name__ == '__main__':
    unittest.main()
