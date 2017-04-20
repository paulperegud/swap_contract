import bitcoin as b
from ethereum import tester, utils


class TestECRecover(object):

    CONTRACT = """
contract Auth {
    function verify(address p, bytes32 hash, uint8 v, bytes32 r, bytes32 s) constant returns(bool) {
        return ecrecover(hash, v, r, s) == p;
    }
}
"""

    def __init__(self):
        self.s = tester.state()
        self.c = self.s.abi_contract(self.CONTRACT, language='solidity')

    def test_ecrecover(self):
        priv = b.sha256('some big long brainwallet password')
        pub = b.privtopub(priv)

        msghash = b.sha256('the quick brown fox jumps over the lazy dog')
        V, R, S = b.ecdsa_raw_sign(msghash, priv)
        assert b.ecdsa_raw_verify(msghash, (V, R, S), pub)

        addr = utils.sha3(b.encode_pubkey(pub, 'bin')[1:])[12:]
        assert utils.privtoaddr(priv) == addr

        result = self.c.test_ecrecover(utils.big_endian_to_int(msghash.decode('hex')), V, R, S)
        assert result == utils.big_endian_to_int(addr)
        assert False

if __name__ == '__main__':
    return
    # x = TestECRecover()
    # x.test_ecrecover()
