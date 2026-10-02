import math
from decimal import ROUND_CEILING, Decimal

from app.config import ModelPrice

MILLION = Decimal(1_000_000)
MICRO = Decimal("0.000001")
BYTES_PER_TOKEN_FLOOR = 2
REQUEST_OVERHEAD_TOKENS = 64


def estimate_input_tokens(*texts: str) -> int:
    total_bytes = sum(len(text.encode("utf-8")) for text in texts)
    return math.ceil(total_bytes / BYTES_PER_TOKEN_FLOOR) + REQUEST_OVERHEAD_TOKENS


def cost_usd(price: ModelPrice, *, input_tokens: int, output_tokens: int) -> Decimal:
    raw = (
        Decimal(input_tokens) * price.input_usd_per_mtok
        + Decimal(output_tokens) * price.output_usd_per_mtok
    ) / MILLION
    return raw.quantize(MICRO, rounding=ROUND_CEILING)


def worst_case_cost(price: ModelPrice, *, input_tokens: int, max_output_tokens: int) -> Decimal:
    return cost_usd(price, input_tokens=input_tokens, output_tokens=max_output_tokens)
