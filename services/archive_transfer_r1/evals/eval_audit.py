"""Compare the replay book to an independent dictionary oracle."""
import random
from decimal import Decimal
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit import Book

rng = random.Random(20261102)
for side, best in (('a', min), ('b', max)):
    book = Book()
    oracle = {}
    for _ in range(20000):
        whole = rng.randrange(1, 201)
        price = Decimal(f"{whole}.123456789012345678901234567891") if whole % 2 else Decimal(whole) / 10
        quantity = rng.randrange(4)
        if quantity:
            oracle[price] = quantity
        else:
            oracle.pop(price, None)
        message = {'a': [], 'b': []}
        message[side] = [[str(price), str(quantity)]]
        book.apply(message, False)
        assert book.best(side) == (best(oracle) if oracle else None)
        assert book.levels[side] == oracle
print('PASS: 40000 updates matched the oracle')
