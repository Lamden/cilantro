from cilantro_ee.nodes.masternode.new_mn import NewMasternode
from unittest import TestCase
from cilantro_ee.core.sockets.services import _socket
from cilantro_ee.services.overlay.discovery import *
from cilantro_ee.services.overlay.discovery import DiscoveryServer
from cilantro_ee.constants.overlay_network import PEPPER
import zmq
import zmq.asyncio
from cilantro_ee.core.crypto.wallet import Wallet
import zmq.asyncio
import asyncio


async def stop_server(s, timeout):
    await asyncio.sleep(timeout)
    s.stop()


class TestNewMasternode(TestCase):
    def setUp(self):
        self.ctx = zmq.asyncio.Context()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.ctx.destroy()
        self.loop.close()

    def test_network_start(self):
        # 4 nodes
        # 2 bootnodes
        # 2 mns, 2 delegates

        bootnodes = ['ipc:///tmp/n1', 'ipc:///tmp/n3']

        mnw1 = Wallet()
        mnw2 = Wallet()
        masternodes = [mnw1.verifying_key().hex(), mnw2.verifying_key().hex()]

        dw1 = Wallet()
        dw2 = Wallet()
        delegates = [dw1.verifying_key().hex(), dw2.verifying_key().hex()]

        n1 = '/tmp/n1'
        make_ipc(n1)
        mn1 = NewMasternode(wallet=mnw1, ctx=self.ctx, socket_base=f'ipc://{n1}',
                      bootnodes=bootnodes, mn_to_find=masternodes, del_to_find=delegates)

        n2 = '/tmp/n2'
        make_ipc(n2)
        mn2 = NewMasternode(wallet=mnw2, ctx=self.ctx, socket_base=f'ipc://{n2}',
                      bootnodes=bootnodes, mn_to_find=masternodes, del_to_find=delegates)

        n3 = '/tmp/n3'
        make_ipc(n3)
        d1 = Network(wallet=dw1, ctx=self.ctx, socket_base=f'ipc://{n3}',
                     bootnodes=bootnodes, mn_to_find=masternodes, del_to_find=delegates)

        n4 = '/tmp/n4'
        make_ipc(n4)
        d2 = Network(wallet=dw2, ctx=self.ctx, socket_base=f'ipc://{n4}',
                     bootnodes=bootnodes, mn_to_find=masternodes, del_to_find=delegates)

        # should test to see all ready signals are recieved
        tasks = asyncio.gather(
            mn1.start(),
            mn2.start(),
            d1.start(),
            d2.start()
        )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(tasks)
