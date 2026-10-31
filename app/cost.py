"""Cost formulas from the guide (section 20). Prices come from environment
variables so the exact model, rates and date checked are recorded in the report."""
import os


def calculate_cost(input_tokens: int, output_tokens: int, input_price: float,
                   output_price: float, cached_tokens: int = 0, cached_price: float = 0.0) -> float:
    """Prices are USD per 1M tokens."""
    return ((input_tokens / 1_000_000) * input_price
            + (output_tokens / 1_000_000) * output_price
            + (cached_tokens / 1_000_000) * cached_price)


def pricing() -> dict:
    return {
        "model": os.getenv("MODEL_NAME", "gemini-2.5-flash-lite"),
        "input_price_per_1m": float(os.getenv("PRICE_INPUT_PER_1M", "0.10")),
        "output_price_per_1m": float(os.getenv("PRICE_OUTPUT_PER_1M", "0.40")),
        "currency": "USD",
        "date_checked": os.getenv("PRICING_DATE_CHECKED", "UNVERIFIED - set PRICING_DATE_CHECKED"),
        "note": "Actual spend is 0 on the free tier; cost shown is the equivalent paid-tier cost.",
    }


def call_cost(input_tokens: int, output_tokens: int) -> float:
    p = pricing()
    return calculate_cost(input_tokens, output_tokens, p["input_price_per_1m"], p["output_price_per_1m"])
