from spotlab.strategies.adaptive import AdaptiveTrendStrategy
from spotlab.strategies.base import Strategy
from spotlab.strategies.regime import RegimeReversionStrategy
from spotlab.strategies.rule_based import RuleBasedStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    "rule_based_v1": RuleBasedStrategy,
    "adaptive_trend_v2": AdaptiveTrendStrategy,
    "regime_reversion_v3": RegimeReversionStrategy,
}


def build_strategy(name: str, **kwargs: object) -> Strategy:
    try:
        strategy_type = STRATEGIES[name]
    except KeyError as error:
        raise ValueError(f"Unknown strategy: {name}") from error
    return strategy_type(**kwargs)


__all__ = ["RuleBasedStrategy", "Strategy", "build_strategy"]
