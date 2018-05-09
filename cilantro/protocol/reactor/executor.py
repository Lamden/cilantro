import asyncio
import zmq.asyncio
from cilantro.logger import get_logger
from cilantro.messages import ReactorCommand, Envelope


# TODO add some API for hooking this stuff up programatically instead of statically defining the callbacks
ROUTE_CALLBACK = 'route'
ROUTE_REQ_CALLBACK = 'route_req'
ROUTE_TIMEOUT_CALLBACK = 'route_timeout'


class ExecutorMeta(type):
    def __new__(cls, clsname, bases, clsdict):
        clsobj = super().__new__(cls, clsname, bases, clsdict)
        clsobj.log = get_logger(clsobj.__name__)

        if not hasattr(clsobj, 'registry'):
            clsobj.registry = {}
        if clsobj.__name__ != 'Executor':
            clsobj.registry[clsobj.__name__] = clsobj

        return clsobj


class Executor(metaclass=ExecutorMeta):
    def __init__(self, loop, context, inproc_socket):
        self.loop = loop
        asyncio.set_event_loop(self.loop)
        self.context = context
        self.inproc_socket = inproc_socket

    async def recv_multipart(self, socket, callback, ignore_first_frame=False):
        self.log.warning("Starting recv on socket {} with callback {}".format(socket, callback))
        while True:
            self.log.debug("waiting for multipart msg...")
            msg = await socket.recv_multipart()
            self.log.debug("Got multipart msg: {}".format(msg))

            if ignore_first_frame:
                header = None
            else:
                assert len(msg) == 2, "ignore_first_frame is false; Expected a multi_msg of len 2 with " \
                                      "(header, envelope) but got {}".format(msg)
                header = msg[0].decode()

            env = msg[-1]
            self._process_envelope(callback, header=header, envelope_binary=env)

    def _process_envelope(self, callback, header, envelope_binary):
        # Validate envelope if this is not a TIMEOUT callback
        if callback != ROUTE_TIMEOUT_CALLBACK:
            self._validate_envelope(envelope_binary, header)

        # Check if this a reply envelope that we have been waiting for, and cancel its callback if so
        if callback == ROUTE_CALLBACK:
            # TODO -- implement
            pass

        # Send callback to main process
        if header:
            cmd = ReactorCommand.create_callback(callback=callback, envelope_binary=envelope_binary, header=header)
        else:
            cmd = ReactorCommand.create_callback(callback=callback, envelope_binary=envelope_binary)
        self.log.debug("Executor sending callback cmd: {}".format(cmd))
        self.inproc_socket.send(cmd.serialize())

    def _validate_envelope(self, envelope_binary, header) -> bool:
        # TODO -- more robust and less ad-hoc zmq multipart msg validation

        # Deserialize envelope
        env = None
        try:
            env = Envelope.from_bytes(envelope_binary)
        except Exception as e:
            self.log.error("\n\n\nError deserializing envelope: {}\n\n\n".format(e))
            return False

        # Check seal
        if not env.verify_seal():
            self.log.error("\n\n\nSeal could not be verified for envelope {}\n\n\n".format(env))
            return False

        # If header is not none (meaning this is a ROUTE msg with an ID frame), then verify that the ID frame is
        # the same as the vk on the seal
        if header and (header != env.seal.verifying_key):
            self.log.error("Header frame {} does not match seal's vk {}\nfor envelope {}"
                           .format(header, env.seal.verifying_key, env))
            return False

        # If none of the above checks returned false, this envelope should be g00d
        return True


class SubPubExecutor(Executor):
    def __init__(self, loop, context, inproc_socket):
        super().__init__(loop, context, inproc_socket)
        self.sub = None
        self.pub = None

    def send_pub(self, filter: str, envelope: bytes):
        assert self.pub, "Attempted to publish data but publisher socket is not configured"
        self.pub.send_multipart([filter.encode(), envelope])

    def add_pub(self, url):
        # TODO -- implement functionality so add_pub will close the existing socket and create a new one if we are switching urls
        if self.pub:
            self.log.error("Attempted to add publisher on url {} but publisher socket already configured.".format(url))
            return

        self.log.info("Creating publisher socket on url {}".format(url))
        self.pub = self.context.socket(socket_type=zmq.PUB)
        self.pub.bind(url)

    def add_sub(self, url: str, filter: str):
        if not self.sub:
            self.log.info("Creating subscriber socket")
            self.sub = self.context.socket(socket_type=zmq.SUB)
            asyncio.ensure_future(self.recv_multipart(self.sub, ROUTE_CALLBACK, ignore_first_frame=True))

        self.log.info("Subscribing to url {} with filter {}".format(url, filter))
        self.sub.connect(url)
        self.sub.setsockopt(zmq.SUBSCRIBE, filter.encode())

    def remove_sub(self, url: str, msg_filter: str):
        assert self.sub, "Remove sub command invoked but sub socket is not set"

        self.sub.setsockopt(zmq.UNSUBSCRIBE, msg_filter.encode())
        self.sub.disconnect(url)

    def remove_pub(self, url: str):
        # TODO -- implement
        self.log.error("remove_pub not implemented")
        raise NotImplementedError


class DealerRouterExecutor(Executor):
    def __init__(self, loop, context, inproc_socket):
        super().__init__(loop, context, inproc_socket)

        # TODO -- make a simple data structure for storing these sockets and their associated futures by key URL
        self.dealers = {}
        self.router = None

    def add_router(self, url):
        assert self.router is None, "Attempted to add router socket on url {} but router socket already configured".format(url)

        self.log.info("Creating router socket on url {}".format(url))
        self.router = self.context.socket(socket_type=zmq.ROUTER)
        self.router.bind(url)
        asyncio.ensure_future(self.recv_multipart(self.router, ROUTE_REQ_CALLBACK))

    def add_dealer(self, url, id):
        assert url not in self.dealers, "Url {} already in self.dealers {}".format(url, self.dealers)
        self.log.info("Creating dealer socket for url {} with id {}".format(url, id))
        self.dealers[url] = self.context.socket(socket_type=zmq.DEALER)
        self.dealers[url].identity = id.encode('ascii')

        # TODO -- store this future so we can cancel it later
        future = asyncio.ensure_future(self.recv_multipart(self.dealers[url], ROUTE_CALLBACK,
                                                           ignore_first_frame=True))

        self.log.info("Dealer socket connecting to url {}".format(url))
        self.dealers[url].connect(url)

    def request(self, url, envelope, timeout=0):
        assert url in self.dealers, "Attempted to make request to url {} that is not in self.dealers {}"\
            .format(url, self.dealers)
        timeout = int(timeout)
        self.log.debug("Composing request to url {}\ntimeout: {}\nenvelope: {}".format(url, timeout, envelope))

        if timeout > 0:
            # TODO -- timeout functionality
            pass

        self.dealers[url].send_multipart([envelope])

    def reply(self, id, envelope):
        # TODO error propgation
        # i  = 10 / 0
        # TODO are we not propagating exceptions properly? This error above does not get outputed in a test..?
        # self.log.critical("\n\n\n\n sending reply to id {} with env {} \n\n\n\n".format(id, envelope))
        assert self.router, "Attempted to reply but router socket is not set"
        self.router.send_multipart([id.encode(), envelope])

    def remove_router(self, url):
        # TODO -- implement
        self.log.critical("remove router not implemented")
        raise NotImplementedError

    def remove_dealer(self, url, id):
        # TODO -- implement
        self.log.critical("remove dealer not implemented")
        raise NotImplementedError