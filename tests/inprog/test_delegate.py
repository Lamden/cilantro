from unittest import TestCase
from cilantro_ee.nodes.delegate.delegate import Delegate
from cilantro_ee.nodes.delegate import execution
from contracting.client import ContractingClient
from contracting.stdlib.bridge.time import Datetime
from cilantro_ee.crypto.wallet import Wallet
from cilantro_ee.crypto.transaction import TransactionBuilder
import time
from cilantro_ee.crypto.transaction_batch import transaction_list_to_transaction_batch
import zmq.asyncio
import datetime
from tests.random_txs import random_block
import os
import capnp
from cilantro_ee.messages.capnp_impl import capnp_struct as schemas
block_capnp = capnp.load(os.path.dirname(schemas.__file__) + '/blockdata.capnp')

class MockDriver:
    def __init__(self):
        self.latest_block_hash = b'\x00' * 32
        self.latest_block_num = 999


class TestExecution(TestCase):
    def setUp(self):
        self.client = ContractingClient()

    def tearDown(self):
        self.client.flush()

    def test_execute_tx_returns_successful_output(self):
        test_contract = '''
v = Variable()

@construct
def seed():
    v.set('hello')

@export
def set(var):
    v.set(var)

@export
def get():
    return v.get()
                '''

        self.client.submit(test_contract, name='testing')

        tx = TransactionBuilder(
            sender='stu',
            contract='testing',
            function='set',
            kwargs={'var': 'jeff'},
            stamps=100_000,
            processor=b'\x00' * 32,
            nonce=0
        )
        tx.sign(Wallet().signing_key())
        tx.serialize()

        result = execution.execute_tx(self.client, tx.struct)

        print(result)

        self.assertEqual(result.status, 0)
        self.assertEqual(result.state[0].key, b'testing.v')
        self.assertEqual(result.state[0].value,  b'"jeff"')
        self.assertEqual(result.stampsUsed, 0)

    def test_generate_environment_creates_datetime_wrapped_object(self):
        timestamp = time.time()

        e = execution.generate_environment(MockDriver(), timestamp, b'A' * 32)

        t = datetime.utcfromtimestamp(timestamp)

        self.assertEqual(type(e['now']), Datetime)
        self.assertEqual(e['now'].year, t.year)
        self.assertEqual(e['now'].month, t.month)
        self.assertEqual(e['now'].day, t.day)
        self.assertEqual(e['now'].hour, t.hour)
        self.assertEqual(e['now'].minute, t.minute)
        self.assertEqual(e['now'].second, t.second)

    def test_generate_environment_creates_input_hash(self):
        timestamp = time.time()

        e = execution.generate_environment(MockDriver(), timestamp, b'A' * 32)

        self.assertEqual(e['__input_hash'], b'A' * 32)

    def test_generate_environment_creates_block_hash(self):
        timestamp = time.time()

        e = execution.generate_environment(MockDriver(), timestamp, b'A' * 32)

        self.assertEqual(e['block_hash'], MockDriver().latest_block_hash.hex())

    def test_generate_environment_creates_block_num(self):
        timestamp = time.time()

        e = execution.generate_environment(MockDriver(), timestamp, b'A' * 32)

        self.assertEqual(e['block_num'], MockDriver().latest_block_num)

    def test_execute_tx_batch_returns_all_transactions(self):
        test_contract = '''
v = Variable()

@construct
def seed():
    v.set('hello')

@export
def set(var):
    v.set(var)

@export
def get():
    return v.get()
        '''

        self.client.submit(test_contract, name='testing')

        tx = TransactionBuilder(
            sender='stu',
            contract='testing',
            function='set',
            kwargs={'var': 'howdy'},
            stamps=100_000,
            processor=b'\x00' * 32,
            nonce=0
        )
        tx.sign(Wallet().signing_key())
        tx.serialize()

        tx2 = TransactionBuilder(
            sender='stu',
            contract='testing',
            function='get',
            kwargs={},
            stamps=100_000,
            processor=b'\x00' * 32,
            nonce=0
        )
        tx2.sign(Wallet().signing_key())
        tx2.serialize()

        tx_batch = transaction_list_to_transaction_batch([tx.struct, tx2.struct], wallet=Wallet())

        results = execution.execute_tx_batch(self.client, MockDriver(), tx_batch, time.time(), b'A'*32)

        td1, td2 = results

        self.assertEqual(td1.status, 0)
        self.assertEqual(td1.state[0].key, b'testing.v')
        self.assertEqual(td1.state[0].value, b'"howdy"')
        self.assertEqual(td1.stampsUsed, 0)

        self.assertEqual(td2.status, 0)
        self.assertEqual(len(td2.state), 0)
        self.assertEqual(td2.stampsUsed, 0)

    def test_execute_work_multiple_transaction_batches_works(self):
        test_contract = '''
v = Variable()

@construct
def seed():
    v.set('hello')

@export
def set(var):
    v.set(var)

@export
def get():
    return v.get()
        '''

        self.client.submit(test_contract, name='testing')

        tx = TransactionBuilder(
            sender='stu',
            contract='testing',
            function='set',
            kwargs={'var': 'howdy'},
            stamps=100_000,
            processor=b'\x00' * 32,
            nonce=0
        )
        tx.sign(Wallet().signing_key())
        tx.serialize()

        tx2 = TransactionBuilder(
            sender='stu',
            contract='testing',
            function='get',
            kwargs={},
            stamps=100_000,
            processor=b'\x00' * 32,
            nonce=0
        )
        tx2.sign(Wallet().signing_key())
        tx2.serialize()

        tx_batch_1 = transaction_list_to_transaction_batch([tx.struct, tx2.struct], wallet=Wallet())

        tx = TransactionBuilder(
            sender='stu',
            contract='testing',
            function='set',
            kwargs={'var': '123'},
            stamps=100_000,
            processor=b'\x00' * 32,
            nonce=0
        )
        tx.sign(Wallet().signing_key())
        tx.serialize()

        tx2 = TransactionBuilder(
            sender='jeff',
            contract='testing',
            function='set',
            kwargs={'var': 'poo'},
            stamps=100_000,
            processor=b'\x00' * 32,
            nonce=0
        )
        tx2.sign(Wallet().signing_key())
        tx2.serialize()

        tx_batch_2 = transaction_list_to_transaction_batch([tx.struct, tx2.struct], wallet=Wallet())

        work = [
            (tx_batch_1.timestamp, tx_batch_1),
            (tx_batch_2.timestamp, tx_batch_2)
        ]

        sbc = execution.execute_work(self.client, MockDriver(), work, Wallet(), b'B'*32)

        sb1, sb2 = sbc

        td1, td2 = sb1.transactions
        self.assertEqual(td1.status, 0)
        self.assertEqual(td1.state[0].key, b'testing.v')
        self.assertEqual(td1.state[0].value, b'"howdy"')
        self.assertEqual(td1.stampsUsed, 0)

        self.assertEqual(td2.status, 0)
        self.assertEqual(len(td2.state), 0)
        self.assertEqual(td2.stampsUsed, 0)

        self.assertEqual(sb1.inputHash, tx_batch_1.inputHash)
        self.assertEqual(sb1.subBlockNum, 0)
        self.assertEqual(sb1.prevBlockHash, b'B'*32)

        td1, td2 = sb2.transactions
        self.assertEqual(td1.status, 0)
        self.assertEqual(td1.state[0].key, b'testing.v')
        self.assertEqual(td1.state[0].value, b'"123"')
        self.assertEqual(td1.stampsUsed, 0)

        self.assertEqual(td2.status, 0)
        self.assertEqual(td2.state[0].key, b'testing.v')
        self.assertEqual(td2.state[0].value, b'"poo"')
        self.assertEqual(td2.stampsUsed, 0)

        self.assertEqual(sb2.inputHash, tx_batch_2.inputHash)
        self.assertEqual(sb2.subBlockNum, 1)
        self.assertEqual(sb2.prevBlockHash, b'B' * 32)


bootnodes = ['ipc:///tmp/n2', 'ipc:///tmp/n3']

mnw1 = Wallet()
mnw2 = Wallet()

dw1 = Wallet()
dw2 = Wallet()
dw3 = Wallet()
dw4 = Wallet()

constitution = {
    "masternodes": {
        "vk_list": [
            mnw1.verifying_key().hex(),
            mnw2.verifying_key().hex()
        ],
        "min_quorum": 1
    },
    "delegates": {
        "vk_list": [
            dw1.verifying_key().hex(),
            dw2.verifying_key().hex(),
            dw3.verifying_key().hex(),
            dw4.verifying_key().hex()
        ],
        "min_quorum": 1
    },
    "witnesses": {},
    "schedulers": {},
    "notifiers": {},
    "enable_stamps": False,
    "enable_nonces": False
}

class TestDelegate(TestCase):
    def setUp(self):
        self.ctx = zmq.asyncio.Context()
        self.client = ContractingClient()

    def tearDown(self):
        self.ctx.destroy()
        self.client.flush()

    def test_init(self):
        b = Delegate(socket_base='tcp://127.0.0.1', wallet=Wallet(), ctx=self.ctx, bootnodes=bootnodes,
                     constitution=constitution)

    def test_did_sign_block_false_if_no_pending_sbcs(self):
        b = Delegate(socket_base='tcp://127.0.0.1', wallet=Wallet(), ctx=self.ctx, bootnodes=bootnodes,
                     constitution=constitution)

        self.assertFalse(b.did_sign_block(None))

    def test_did_sign_block_false_if_missing_any_merkle_roots(self):
        b = Delegate(socket_base='tcp://127.0.0.1', wallet=Wallet(), ctx=self.ctx, bootnodes=bootnodes,
                     constitution=constitution)

        block = random_block()

        # Add one root but not the other
        b.pending_sbcs.add(block.subBlocks[0].merkleRoot)

        self.assertFalse(b.did_sign_block(block))

