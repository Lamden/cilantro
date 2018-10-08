from vmnet.comm import file_listener
from vmnet.testcase import BaseTestCase
import unittest, time, random, vmnet, cilantro, asyncio, ujson as json
from os.path import join, dirname
from cilantro.utils.test.mp_test_case import vmnet_test, wrap_func
from cilantro.logger.base import get_logger
from cilantro.constants.testnet import TESTNET_MASTERNODES, TESTNET_WITNESSES, TESTNET_DELEGATES

def nodefn(node_type, idx):
    from cilantro.constants.testnet import TESTNET_MASTERNODES, TESTNET_WITNESSES, TESTNET_DELEGATES
    from cilantro.protocol.overlay.daemon import OverlayServer
    from cilantro.constants.overlay_network import MIN_BOOTSTRAP_NODES
    from multiprocessing import Process
    from vmnet.comm import send_to_file
    import asyncio, json, os, zmq.asyncio, asyncio

    def client(nt, i):
        from cilantro.protocol.overlay.daemon import OverlayClient
        from cilantro.logger.base import get_logger
        import os, asyncio
        log = get_logger('{}{}'.format(nt, i+1))
        def handler(data):
            if data['event'] == 'got_ip':
                data['hostname'] = os.getenv('HOST_NAME')
                send_to_file(json.dumps(data))
        async def lookup_ip():
            await asyncio.sleep(5)
            for vk in [
                *[node['vk'] for node in TESTNET_MASTERNODES],
                *[node['vk'] for node in TESTNET_WITNESSES],
                *[node['vk'] for node in TESTNET_DELEGATES]
            ]:
                client.get_node_from_vk(vk)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ctx = zmq.asyncio.Context()
        client = OverlayClient(handler, ctx=ctx)
        client.tasks.append(lookup_ip())
        client.start()

    p = Process(target=client, args=(node_type, idx, ))
    p.start()
    loop = asyncio.get_event_loop()
    if node_type == 'MasterNode':
        server = OverlayServer(TESTNET_MASTERNODES[idx]['sk'], loop=loop)
    elif node_type == 'Witness':
        server = OverlayServer(TESTNET_WITNESSES[idx]['sk'], loop=loop)
    elif node_type == 'Delegate':
        server = OverlayServer(TESTNET_DELEGATES[idx]['sk'], loop=loop)
    server.start()

class TestDaemon(BaseTestCase):

    log = get_logger(__name__)
    config_file = join(dirname(cilantro.__path__[0]), 'vmnet_configs', 'cilantro-2-4-4-bootstrap.json')

    def callback(self, data):
        for s in data:
            d = json.loads(s)
            if not self.nodes_got_ip.get(d['hostname']):
                self.nodes_got_ip[d['hostname']] = set()
            self.nodes_got_ip[d['hostname']].add(d['vk'])

    def complete(self):
        all_vks = set([
            *[node['vk'] for node in TESTNET_MASTERNODES],
            *[node['vk'] for node in TESTNET_WITNESSES],
            *[node['vk'] for node in TESTNET_DELEGATES]
        ])
        all_hostnames = self.groups['masternode'] + self.groups['witness'] + self.groups['delegate']
        for hostname in all_hostnames:
            self.assertEqual(self.nodes_got_ip[hostname], all_vks)

    def test_daemon(self):
        self.nodes_got_ip = {}
        for idx, node in enumerate(self.groups['masternode']):
            self.execute_python(node, wrap_func(nodefn, 'MasterNode', idx))
        for idx, node in enumerate(self.groups['witness']):
            self.execute_python(node, wrap_func(nodefn, 'Witness', idx))
        for idx, node in enumerate(self.groups['delegate']):
            self.execute_python(node, wrap_func(nodefn, 'Delegate', idx))

        file_listener(self, self.callback, self.complete, 15)

if __name__ == '__main__':
    unittest.main()