from pathlib import Path
import uuid
import shutil
import os
from contracting.db.encoder import decode
from lamden.logger.base import get_logger

class FileQueue:
    EXTENSION = '.tx'

    def __init__(self, root='./txs'):
        self.log = get_logger('FILE QUEUE')
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, tx):
        name = str(uuid.uuid4()) + self.EXTENSION
        self.log.debug(f'Saving to {self.root.joinpath(name)}')
        with open(self.root.joinpath(name), 'wb') as f:
            f.write(tx)

    def pop(self, idx):
        items = sorted(self.root.iterdir(), key=os.path.getmtime)
        item = items.pop(idx)

        with open(item) as f:
            i = decode(f.read())

        os.remove(item)
        self.log.debug(i)
        return i

    def flush(self):
        shutil.rmtree(self.root)

    def __len__(self):
        try:
            length = len(list(self.root.iterdir()))
            return length
        except FileNotFoundError:
            return 0