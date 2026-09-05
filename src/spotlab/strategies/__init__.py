from spotlab.strategies.adaptive import AdaptiveTrendStrategy
from spotlab.strategies.base import Strategy
from spotlab.strategies.rule_based import RuleBasedStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    "rule_based_v1": RuleBasedStrategy,
    "adaptive_trend_v2": AdaptiveTrendStrategy,
}


def build_strategy(name: str, **kwargs: object) -> Strategy:
    try:
        strategy_type = STRATEGIES[name]
    except KeyError as error:
        raise ValueError(f"Unknown strategy: {name}") from error
    return strategy_type(**kwargs)


__all__ = ["RuleBasedStrategy", "Strategy", "build_strategy"]
