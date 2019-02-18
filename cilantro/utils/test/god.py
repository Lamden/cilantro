from cilantro.messages.transaction.container import TransactionContainer
from cilantro.messages.transaction.publish import *
from cilantro.messages.transaction.contract import *
from cilantro.messages.signals.kill_signal import KillSignal

from cilantro.logger import get_logger
from cilantro.utils.test.utils import *
from cilantro.utils.test.wallets import ALL_WALLETS
import os, requests, time, random, asyncio, secrets


class God:
    # For MP tests  TODO i dont think we need this  --davis
    node_map = None
    testers = []

    log = get_logger("GOD")

    mn_urls = get_mn_urls()
    multi_master = type(mn_urls) is list  # If True, outgoing transactions will be round-robined to all masternodes
    _current_mn_idx = 0

    def __init__(self):
        raise NotImplementedError("Use only class method on God")

    @classmethod
    def _default_gen_func(cls):
        return cls.random_contract_tx

    @classmethod
    def set_mn_url(cls, ip='localhost', port=8080):
        raise NotImplementedError("This is deprecated!!!")

    @classmethod
    def create_currency_tx(cls, sender: tuple, receiver: tuple, amount: int, stamps=100000, nonce=None):
        if type(receiver) is tuple:
            receiver = receiver[1]

        return ContractTransactionBuilder.create_currency_tx(sender[0], receiver, amount, stamps=stamps, nonce=nonce)

    @classmethod
    def send_currency_contract(cls, sender: tuple, receiver: tuple, amount: int):
        tx = cls.create_currency_tx(sender, receiver, amount)
        return cls.send_tx(tx)

    @classmethod
    def send_tx(cls, tx: TransactionBase):
        mn_url = cls._get_mn_url()
        try:
            r = requests.post(mn_url, data=TransactionContainer.create(tx).serialize(), verify=False)
            cls.log.spam("POST request to MN at URL {} has status code: {}".format(mn_url, r.status_code))
            return r
        except Exception as e:
            cls.log.warning("Error attempt to send transaction to Masternode at URL {}\nerror={}".format(mn_url, e))
            return None

    @classmethod
    def pump_it(cls, rate: int, gen_func=None, use_poisson=True, sleep_sometimes=False, active_bounds=(120, 240),
                sleep_bounds=(20, 60), pump_wait=0):
        """
        Pump random transactions from random users to Masternode's REST endpoint at an average rate of 'rate'
        transactions per second. This func blocks.
        """
        God.mn_urls = get_mn_urls()  # Reset MN URLS
        if pump_wait > 0:
            cls.log.important("Pumper sleeping {} seconds before starting...".format(pump_wait))
            time.sleep(pump_wait)

        if not gen_func:
            gen_func = cls._default_gen_func()

        if use_poisson:
            from scipy.stats import poisson, expon
            rvs_func = lambda: expon.rvs(rate)/rate - 1
        else:
            rvs_func = lambda: 1/rate

        assert callable(gen_func), "Expected a callable for 'gen_func' but got {}".format(gen_func)

        cls.log.important3("Starting to pump transactions at an average of {} transactions per second".format(rate))
        cls.log.test("Using generator func {}, use_possion={}, sleep_sometimes={}, active_bounds={}, sleep_bounds={}"
                     .format(gen_func, use_poisson, sleep_sometimes, active_bounds, sleep_bounds))

        time_since_last_sleep = 0
        next_sleep = random.randint(active_bounds[0], active_bounds[1])
        if sleep_sometimes:
            cls.log.important3("Next sleep will be in {}s".format(next_sleep))

        while True:
            wait = rvs_func()
            # cls.log.spam("Sending next transaction in {} seconds".format(wait))
            time.sleep(wait)
            time_since_last_sleep += wait

            tx = gen_func()
            # cls.log.spam("sending transaction {}".format(tx))
            cls.send_tx(tx)

            if sleep_sometimes and time_since_last_sleep >= next_sleep:
                sleep_time = random.randint(sleep_bounds[0], sleep_bounds[1])
                cls.log.important3("Sleeping for {}s before pumping more...")
                time.sleep(sleep_time)

                time_since_last_sleep = 0
                next_sleep = random.randint(active_bounds[0], active_bounds[1])
                cls.log.important3("Done sleeping. Continuing the pump, and triggering next sleep in {}s".format(next_sleep))

    @classmethod
    def dump_it(cls, volume: int, delay: int=0, gen_func=None):
        """ Dump it fast. """
        # God.mn_urls = get_mn_urls()  # Reset MN URLS
        assert volume > 0, "You must dump at least 1 transaction silly"

        if not gen_func:
            gen_func = cls._default_gen_func()

        gen_start_time = time.time()
        cls.log.important2("Generating {} transactions to dump...".format(volume))
        txs = [gen_func() for _ in range(volume)]
        cls.log.important2("Done generating transactions.")

        delay -= int(time.time() - gen_start_time)
        countdown(delay, "Waiting for an additional {} seconds before dumping...", cls.log, status_update_freq=8)

        start = time.time()
        cls.log.info("Dumping {} transactions...".format(len(txs)))
        for tx in txs:
            cls.send_tx(tx)
        cls.log.success("Done dumping {} transactions in {} seconds".format(len(txs), round(time.time() - start, 3)))

    @classmethod
    def request_nonce(cls, vk):
        mn_url = cls._get_mn_url() + '/nonce'
        try:
            r = requests.get(mn_url, json={'verifyingKey': vk})
            cls.log.debugv("GET request to MN at URL {} has status code: {}".format(mn_url, r.status_code))
            return r.json()

        except Exception as e:
            cls.log.warning("Error attempt to send transaction to Masternode at URL {}\nerror={}".format(mn_url, e))
            return 'error: {}'.format(e)

    @classmethod
    def random_contract_tx(cls):
        sender, receiver = random.sample(ALL_WALLETS, 2)
        amount = random.randint(1, 100)

        return cls.create_currency_tx(sender=sender, receiver=receiver, amount=amount)

    @classmethod
    def get_random_mn_url(cls):
        return random.choice(cls.mn_urls)

    @classmethod
    def get_from_mn_api(cls, query_str, enforce_consistency=True, req_type='json'):
        def _parse_reply(req, req_type='json'):
            if req.status_code != 200:
                cls.log.spam("Got status code {} from request {}".format(req.status_code, req))
                return None

            if req_type == 'json':
                return req.json()
            else:
                raise Exception("Unknown request type {}".format(req_type))

        if not enforce_consistency:
            return _parse_reply(requests.get("{}/{}".format(cls.get_random_mn_url(), query_str)))

        replies = {}
        for mn_url in cls.mn_urls:
            replies[mn_url] = _parse_reply(requests.get("{}/{}".format(mn_url, query_str)))
        reply_vals = list(replies.values())

        if all(x == reply_vals[0] for x in reply_vals):
            return reply_vals[0]
        else:
            cls.log.warning("Masternodes had inconsistent replies for GET request {} ... possibile state"
                            " corruption!?\nReplies: {}".format(query_str, replies))
            return None

    @classmethod
    def submit_contract(cls, code: str, name: str, sk: str, vk: str, stamps=10**6):
        tx = PublishTransaction.create(contract_code=code,
                                       contract_name=name,
                                       sender_sk=sk,
                                       nonce=vk + secrets.token_hex(32),
                                       stamps_supplied=stamps)
        return cls.send_tx(tx)

    @classmethod
    def get_contracts(cls):
        return cls.get_from_mn_api('/contracts')

    @classmethod
    def get_contract_meta(cls, contract_name: str):
        return cls.get_from_mn_api('/contracts/{}'.format(contract_name))

    @classmethod
    def get_contract_resources(cls, contract_name: str):
        return cls.get_from_mn_api('/contracts/{}/resources'.format(contract_name))

    @classmethod
    def get_contract_methods(cls, contract_name: str):
        return cls.get_from_mn_api('/contracts/{}/methods'.format(contract_name))

    @classmethod
    def _get_mn_url(cls):
        if cls.multi_master:
            mn_url = cls.mn_urls[cls._current_mn_idx]
            cls._current_mn_idx = (cls._current_mn_idx + 1) % len(cls.mn_urls)
            cls.log.debug("Multi-master detected. Using Masternode at IP {}".format(mn_url))
        else:
            mn_url = cls.mn_urls[0]

        return mn_url

