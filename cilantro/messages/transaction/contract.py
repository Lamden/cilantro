from cilantro.messages.transaction.base import TransactionBase
from cilantro.messages.utils import validate_hex
from cilantro.protocol import wallet
from cilantro.storage.templating import ContractTemplate
from cilantro.protocol.pow import SHA3POW

import capnp
import transaction_capnp

import random


class ContractTransaction(TransactionBase):
    """
    ContractTransactions are sent into the system by users who wish to execute smart contracts. IRL, they should be
    build by some front end framework/library. Apart from the metadata, they contain one field called "code", which
    represents the code of the smart contract to be run, as plain text.
    """

    def validate_payload(self):
        validate_hex(self.sender, 64, 'sender')

    @classmethod
    def _deserialize_data(cls, data: bytes):
        return transaction_capnp.ContractTransaction.from_bytes_packed(data)

    @property
    def code(self):
        return self._data.payload.code

    @property
    def sender(self):
        return self._data.payload.sender.decode()

    @property
    def contract_name(self):
        return self._data.contractName.decode()

    @property
    def gas_supplied(self):
        return self._data.gasSupplied


class ContractTransactionBuilder:
    """
    Utility methods to construct ContractTransactions. We use this exclusively for testing, as IRL this should be done by
    users via some JS library or something.
    """
    @staticmethod
    def create_contract_tx(sender_sk: str, code_str: str, contract_name: str='sample', gas_supplied: int=1.0):
        validate_hex(sender_sk, 64, 'sender signing key')

        struct = transaction_capnp.ContractTransaction.new_message()

        struct.payload.sender = wallet.get_vk(sender_sk)
        struct.payload.code = code_str
        struct.payload.gasSupplied = gas_supplied

        payload_binary = struct.payload.copy().to_bytes()

        struct.metadata.proof = SHA3POW.find(payload_binary)[0]
        struct.metadata.signature = wallet.sign(sender_sk, payload_binary)
        struct.contractName = contract_name

        return ContractTransaction.from_data(struct)

    @staticmethod
    def create_currency_tx(sender_sk: str, receiver_vk: str, amount: int):

        validate_hex(receiver_vk, 64, 'receiver verifying key')
        code_str = ContractTemplate.interpolate_template('currency', amount=amount, receiver=receiver_vk)
        return ContractTransactionBuilder.create_contract_tx(sender_sk, code_str)

    @staticmethod
    def random_currency_tx():
        from cilantro.utils.test.god import ALL_WALLETS
        import random

        sender, receiver = random.sample(ALL_WALLETS, 2)
        amount = random.randint(1, 2 ** 8)
        return ContractTransactionBuilder.create_currency_tx(sender[0], receiver[1], amount)

    @staticmethod
    def create_dummy_tx(sender_sk: str, receiver_vk: str, fail: bool):

        code_str = ContractTemplate.interpolate_template('dummy', fail=fail)
        return ContractTransactionBuilder.create_contract_tx(sender_sk, code_str)
