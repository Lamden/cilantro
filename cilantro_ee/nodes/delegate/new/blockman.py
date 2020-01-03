from cilantro_ee.services.storage.vkbook import VKBook
from cilantro_ee.services.storage.state import MetaDataStorage
from cilantro_ee.core.networking.parameters import ServiceType, NetworkParameters, Parameters
from cilantro_ee.core.sockets.services import AsyncInbox

from cilantro_ee.core.messages.message import Message
from cilantro_ee.core.messages.message_type import MessageType

from cilantro_ee.core.containers.merkle_tree import MerkleTree

from cilantro_ee.core.crypto.wallet import _verify, Wallet

from contracting.client import ContractingClient
from contracting.stdlib.bridge.decimal import ContractingDecimal
from contracting.stdlib.bridge.time import Datetime
from contracting.db.encoder import encode

import time
import asyncio
import heapq
from datetime import datetime
import zmq.asyncio


class BlockNotificationException(Exception):
    pass


class BlockNumberMismatch(BlockNotificationException):
    pass


class InvalidMessageType(BlockNotificationException):
    pass


class NBNInbox(AsyncInbox):
    def __init__(self, contacts, driver, *args, **kwargs):
        self.q = []
        self.contacts = contacts
        self.driver = driver
        super().__init__(*args, **kwargs)

    async def handle_msg(self, _id, msg):
        #msg_type, msg_blob = Message.unpack_message_2(msg)

        #if msg_type != MessageType.BLOCK_NOTIFICATION:
        #    return

        # Make sure it's legit
        #if msg_blob.blockNum < self.driver.latest_block_num + 1:
        #    return

        # If sender isnt a masternode, return
        #if sender.hex() not in self.contacts.masternodes:
        #    return

        # if 2 / 3 didnt sign, return
        #sub_blocks = [sb for sb in block.subBlocks]
        #for sb in sub_blocks:
        #    if len(sb.signatures) < len(self.contacts.delegates) * 2 // 3:
        #        return

        self.q.append(msg)

    def block_notification_is_valid(self, msg):
        msg_type, msg_blob, _, _, _ = Message.unpack_message_2(msg)

        if msg_type != MessageType.BLOCK_NOTIFICATION:
            raise InvalidMessageType

        if msg_blob.blockNum < self.driver.latest_block_num + 1:
            raise BlockNumberMismatch

    async def wait_for_next_nbn(self):
        while len(self.q) <= 0:
            await asyncio.sleep(0)

        nbn = self.q.pop(0)
        self.q.clear()

        return nbn


class WorkInbox(AsyncInbox):
    def __init__(self, validity_timeout, contacts: VKBook, *args, **kwargs):
        self.work = {}
        self.validity_timeout = validity_timeout
        self.contacts = contacts

        self.current_masternodes = self.contacts.masternodes
        super().__init__(*args, **kwargs)

    def handle_msg(self, _id, msg):
        msg_type, msg_struct = Message.unpack_message_2(msg)

        # Ignore everything except TX Batches
        if msg_type != MessageType.TRANSACTION_BATCH:
            return

        # Ignore if the tx batch is too old
        if time.time() - msg_struct.timestamp > self.validity_timeout:
            return

        # Ignore if the tx batch is not signed by the right sender
        if not _verify(vk=msg_struct.sender,
                       signature=msg_struct.signature,
                       msg=msg_struct.inputHash):
            return

        self.work[msg_struct.sender.hex()] = msg_struct

    async def wait_for_next_batch_of_work(self):
        self.work.clear()
        self.current_masternodes = self.contacts.masternodes
        # Wait for work from all masternodes that are currently online
        # How do we test if they are online? idk.
        while len(set(self.current_masternodes) - set(self.work.keys())) > 0:
            await asyncio.sleep(0)

        return self.work


class BlockManager:
    def __init__(self, socket_base, ctx, wallet: Wallet, network_parameters: NetworkParameters,
                 contacts: VKBook, validity_timeout=1000, parallelism=4, client=ContractingClient(),
                 driver=MetaDataStorage()):

        # VKBook, essentially
        self.contacts = contacts
        self.parameters = Parameters(
            socket_base=socket_base,
            ctx=ctx,
            wallet=wallet,
            network_parameters=network_parameters,
            contacts=self.contacts)

        # Number of core / processes we push to
        self.parallelism = parallelism
        self.network_parameters = network_parameters
        self.ctx = ctx
        self.wallet = wallet

        # How long until a tx batch is 'stale' and no longer valid
        self.validity_timeout = validity_timeout

        self.client = client
        self.driver = driver

        self.nbn_inbox = NBNInbox(
            socket_id=self.network_parameters.resolve(socket_base, ServiceType.BLOCK_NOTIFICATIONS, bind=True)
        )
        self.work_inbox = WorkInbox(
            socket_id=self.network_parameters.resolve(socket_base, ServiceType.INCOMING_WORK, bind=True)
        )
        self.pending_sbc = None
        self.running = False

    async def send_out(self, msg, socket_id):
        socket = self.ctx.socket(zmq.DEALER)
        socket.connect(str(socket_id))

        try:
            socket.send(msg, zmq.NOBLOCK)
            return True
        except zmq.ZMQError:
            return False

    async def run(self):
        while self.running:
            # wait for NBN
            block = await self.nbn_inbox.wait_for_next_nbn()


            # If its the block that you worked on, commit the db
            # AKA if you signed the block

            # Else, revert the db and Catchup with block
            # Block has already been verified to be in 2/3 consensus at this point
            self.catchup_with_new_block(block, sender=b'')

            # Request work. Use async / dealers to block until it's done?
            # Refresh sockets here
            # Turn this into a new message type
            work = await self.work_inbox.wait_for_next_batch_of_work()

            filtered_work = []
            for tx_batch in work:
                # Filter out None responses
                if tx_batch is None:
                    continue

                # Add the rest to a priority queue based on their timestamp
                heapq.heappush(filtered_work, (tx_batch.timestamp, tx_batch))

            # Execute work
            results = await self.execute_work(filtered_work)

            # Package as SBCs
            sbcs_msg_blob = Message.get_message_packed_2(
                msg_type=MessageType.SUBBLOCK_CONTENDERS,
                contenders=[sb for sb in results]
            )

            # Send SBCs to masternodes
            tasks = []
            for k, v in self.parameters.get_masternode_sockets(service=ServiceType.BLOCK_AGGREGATOR):
                tasks.append(self.send_out(sbcs_msg_blob, v))

            await asyncio.gather(*tasks)

    # Do this verification shit in the NBN inbox
    def catchup_with_new_block(self, block, sender: bytes):

            # if you're not in the signatures, run catchup
            # if you are in the signatures, commit db
        pass

    async def execute_work(self, work):
        # Assume single threaded, single process for now.
        results = []
        i = 0

        while len(work) > 0:
            tx_batch = heapq.heappop(work)
            transactions = [tx for tx in tx_batch.transactions]

            now = Datetime._from_datetime(
                datetime.utcfromtimestamp(tx_batch.timestamp)
            )

            environment = {
                'block_hash': self.driver.latest_block_hash.hex(),
                'block_num': self.driver.latest_block_num,
                '__input_hash': tx_batch.inputHash, # Used for deterministic entropy for random games
                'now': now
            }

            # Each TX Batch is basically a subblock from this point of view and probably for the near future
            tx_data = []
            for transaction in transactions:
                # Deserialize Kwargs. Kwargs should be serialized JSON moving into the future for DX.
                kwargs = {}
                for entry in transaction.payload.kwargs.entries:
                    if entry.value.which() == 'fixedPoint':
                        kwargs[entry.key] = ContractingDecimal(entry.value.fixedPoint) # ContractingDecimal!
                    else:
                        kwargs[entry.key] = getattr(entry.value, entry.value.which())

                output = self.client.executor.execute(
                    sender=transaction.payload.sender.hex(),
                    contract_name=transaction.payload.contractName,
                    function_name=transaction.payload.functionName,
                    stamps=transaction.payload.stampsSupplied,
                    kwargs=kwargs,
                    environment=environment,
                    auto_commit=False
                )

                # If we keep a running total, we just have to do a single update per subblock in the case of overlapping keys
                # This would save time
                tx_data.append(
                    Message.get_message(
                        msg_type=MessageType.TRANSACTION_DATA,
                        transaction=transaction,
                        status=output['status_code'],
                        state=encode(output['writes'])
                    )
                )

            sbc = self.build_sbc_from_work_results(
                input_hash=tx_batch.inputHash,
                results=tx_data,
                sb_num=i % self.parallelism
            )

            results.append(sbc)
            i += 1

        return results

    def build_sbc_from_work_results(self, input_hash, results, sb_num=0):
        # build sbc
        merkle = MerkleTree.from_raw_transactions(results)

        _, merkle_proof = Message.get_message(
            MessageType.MERKLE_PROOF,
            hash=merkle.root,
            signer=self.wallet.verifying_key(),
            signature=self.wallet.sign(merkle.root))

        sbc = Message.get_message(
            MessageType.SUBBLOCK_CONTENDER,
            resultHash=merkle.root,
            inputHash=input_hash,
            merkleLeaves=[leaf for leaf in merkle.leaves],
            signature=merkle_proof,
            transactions=[tx for tx in results],
            subBlockNum=sb_num,
            prevBlockHash=self.driver.latest_block_hash
        )

        return sbc
