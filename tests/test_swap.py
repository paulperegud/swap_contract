import math
import os
import random
import unittest
from collections import deque
from contextlib import contextmanager
from random import randint
from os import urandom

import re
import bitcoin
from ethereum import abi, tester, utils
from ethereum.config import default_config
from ethereum.tester import TransactionFailed, ContractCreationFailed
from ethereum.utils import denoms, privtoaddr, to_string, parse_int_or_hex, mk_contract_address
import ethereum.utils
from secp256k1 import PublicKey, ALL_FLAGS, PrivateKey
from rlp.utils import decode_hex, encode_hex

tester.serpent = True  # tester tries to load serpent module, prevent that.

GNT_INIT = decode_hex(open('tests/GolemNetworkToken.bin', 'r').read().rstrip())
GNT_ABI = open('tests/GolemNetworkToken.abi', 'r').read()

SWAP_INIT = decode_hex(open('tests/GolemSecretForPaymentSwap.bin', 'r').read().rstrip())
SWAP_ABI = open('tests/GolemSecretForPaymentSwap.abi', 'r').read()

gwei = 10 ** 9

tester.gas_limit = int(1.9 * 10 ** 6)
tester.gas_price = int(20 * gwei)

@contextmanager
def work_dir_context(file_path):
    cwd = os.getcwd()
    file_name = os.path.basename(file_path)
    rel_dir = os.path.dirname(file_path) or '.'
    dir_name = os.path.abspath(rel_dir)

    os.chdir(dir_name)
    yield file_name
    os.chdir(cwd)

class GNTCrowdfundingTest(unittest.TestCase):

    # Test account monitor.
    # The ethereum.tester predefines 10 Ethereum accounts
    # (tester.accounts, tester.keys).
    class Monitor:
        def __init__(self, state, account_idx, value=0):
            self.addr = tester.accounts[account_idx]
            self.key = tester.keys[account_idx]
            self.state = state
            self.value = value
            self.initial = state.block.get_balance(self.addr)
            assert self.initial > 0
            assert self.addr != state.block.coinbase

        def gas(self):
            b = self.state.block.get_balance(self.addr)
            total = self.initial - b
            g = (total - self.value) / tester.gas_price
            return g

    class EventListener:
        def __init__(self, contract, state):
            self.contract = contract
            self.state = state
            self.events = deque()

        def hook(self):
            self.state.block.log_listeners.append(self._listen)

        def unhook(self):
            listeners = self.state.block.log_listeners
            if self._listen in listeners:
                listeners.remove(self._listen)

        def event(self, event_type, **params):
            if self.events:
                event = self.events.popleft()  # FIFO
                type_matches = event["_event_type"] == event_type
                return type_matches and all([event.get(n) == v for n, v in params.items()])

        def _listen(self, event):
            self.events.append(self.contract.translator.listen(event))

    def monitor(self, addr, value=0):
        return self.Monitor(self.state, addr, value)

    def contract_balance(self):
        return self.state.block.get_balance(self.c.address)

    def balance_of(self, addr_idx):
        return self.c.balanceOf(tester.accounts[addr_idx])

    def transfer(self, sender, to, value):
        return self.c.transfer(to, value, sender=sender)

    def is_funding_active(self):
        """ Checks if the crowdfunding contract is in Funding Active state."""
        if not self.c.funding():
            return False

        n = self.state.block.number
        s = self.c.fundingStartBlock()
        e = self.c.fundingEndBlock()
        m = self.c.tokenCreationCap()
        t = self.c.totalSupply()
        return s <= n <= e and t < m

    def number_of_tokens_left(self):
        return self.c.tokenCreationCap() - self.c.totalSupply()

    def setUp(self):
        self.state = tester.state()
        self.starting_block = default_config.get('ANTI_DOS_FORK_BLKNUM') + 1
        self.state.block.number = self.starting_block

    def deploy_swap(self, provider, creator_idx=9):
        owner = self.monitor(creator_idx)
        t = abi.ContractTranslator(SWAP_ABI)
        args = t.encode_constructor_arguments((provider,))
        addr = self.state.evm(SWAP_INIT + args,
                              sender=owner.key)
        self.s = tester.ABIContract(self.state, SWAP_ABI, addr)
        return addr, owner.gas()

    def test_swap_deployment(self):
        founder = tester.accounts[2]
        addr, gas = self.deploy_swap(founder)
        print("deployment cost: {}".format(gas))

    def test_finalize_gas(self):
        r_priv = tester.keys[9]
        r_pub = bitcoin.privtopub(r_priv)
        r_addr = tester.accounts[9]
        p_priv = tester.keys[2]
        p_pub = bitcoin.privtopub(p_priv)
        p_addr = tester.accounts[2]
        swap_contract_addr, _ = self.deploy_swap(p_addr)
        random.seed(0)
        kdf_seed = random.getrandbits(32*8)
        i = random.randint(1, 100)
        def cpack(n, bts):
            import struct
            fmt = "!{}B".format(n)
            return struct.pack(fmt, *[bts >> i & 0xff for i in reversed(range(0, n*8, 8)) ])
        # secret represents partial evaluation of KDF derivation function
        # where KDF(kdf_seed, i) = sha3(kdf_seed ++ i)
        secret = cpack(30, kdf_seed) + cpack(2, i)
        assert len(secret) == 32
        value = random.randint(1, 1000000000)
        # in Solidity: sha3(sha3(secret), bytes32(_value)):
        msghash = utils.sha3(utils.sha3(secret) + cpack(32, value))
        (V, R, S) = sign_btc(msghash, r_priv, r_pub)
        assert (V, R, S) == sign_eth(msghash, r_priv)
        ER = cpack(32, R)
        ES = cpack(32, S)
        self.s.finalize(secret, value, ER, ES, V, sender=p_priv)

def sign_eth(rawhash, priv):
    pk = PrivateKey(priv, raw=True)
    signature = pk.ecdsa_recoverable_serialize(
        pk.ecdsa_sign_recoverable(rawhash, raw=True)
    )
    signature = signature[0] + utils.bytearray_to_bytestr([signature[1]])
    v = utils.safe_ord(signature[64]) + 27
    r = utils.big_endian_to_int(signature[0:32])
    s = utils.big_endian_to_int(signature[32:64])
    return (v, r, s)

def sign_btc(msghash, priv, pub):
    V, R, S = bitcoin.ecdsa_raw_sign(msghash, priv)
    assert bitcoin.ecdsa_raw_verify(msghash, (V, R, S), pub)
    Q = bitcoin.ecdsa_raw_recover(msghash, (V, R, S))
    assert addr == bitcoin.encode_pubkey(Q, 'hex_compressed') if V >= 31 else bitcoin.encode_pubkey(Q, 'hex')
    return (V, R, S)
