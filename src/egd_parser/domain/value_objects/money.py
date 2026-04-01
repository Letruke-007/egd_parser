from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class MoneyValue:
    amount: Decimal
    currency: str = "RUB"
