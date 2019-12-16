from cilantro_ee.nodes.masternode.masternode import Masternode
from cilantro_ee.nodes.delegate.delegate import Delegate
from cilantro_ee.constants import conf
from cilantro_ee.nodes.base import Node2, NewMasternode

import time
from pymongo import MongoClient

import asyncio
import zmq.asyncio

MASTERNODE = 0
DELEGATE = 1
WITNESS = 2


def wait_for_redis():
    time.sleep(2)


def wait_for_mongo():
    while True:
        try:
            info = MongoClient().server_info()
            print("Mongo ready! Server info:\n{}".format(info))
            break
        except:
            print("Waiting for Mongo to be ready...")
            time.sleep(1)


def start_node(signing_key, node_type):
    wait_for_redis()

    if node_type == MASTERNODE:
        wait_for_mongo()

        ctx = zmq.asyncio.Context()
        n = NewMasternode(conf.HOST_IP, ctx=ctx, signing_key=signing_key, name='Masternode')
        loop = asyncio.get_event_loop()
        loop.run_until_complete(n.start())

        # Masternode(ip=conf.HOST_IP, name='Masternode', signing_key=signing_key)

    elif node_type == DELEGATE:
        ctx = zmq.asyncio.Context()
        n = Node2(conf.HOST_IP, ctx=ctx, signing_key=signing_key, name='Delegate')
        loop = asyncio.get_event_loop()
        loop.run_until_complete(n.start())
        # Delegate(ip=conf.HOST_IP, name='Delegate', signing_key=signing_key)
