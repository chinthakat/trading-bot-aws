
import importlib
import pkgutil
import inspect
import logging
from typing import Dict, Type
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

class StrategyLoader:
    """Dynamic loader for strategy plugins."""
    
    _strategies: Dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def discover_strategies(cls):
        """Scan the 'strategies' package for plugins."""
        import strategies
        
        path = strategies.__path__
        prefix = strategies.__name__ + "."

        for _, name, _ in pkgutil.iter_modules(path, prefix):
            try:
                logger.info(f"Attempting to load strategy module: {name}")
                module = importlib.import_module(name)
                # Scan module for classes inheriting BaseStrategy
                found_in_module = False
                for attr_name, attr_value in inspect.getmembers(module):
                    if (inspect.isclass(attr_value) 
                        and issubclass(attr_value, BaseStrategy) 
                        and attr_value is not BaseStrategy):
                        
                        # Use class attribute 'name' or fallback to class name
                        strat_name = getattr(attr_value, "NAME", attr_value.__name__)
                        cls._strategies[strat_name] = attr_value
                        logger.info(f"Loaded strategy plugin: {strat_name} from {name}")
                        found_in_module = True
                
                if not found_in_module:
                    logger.warning(f"No valid strategy class found in module {name}")
                        
            except Exception as e:
                logger.error(f"Failed to load strategy module {name}: {e}")

    @classmethod
    def get_strategy(cls, name: str, config: dict) -> BaseStrategy:
        if not cls._strategies:
            cls.discover_strategies()
            
        strategy_class = cls._strategies.get(name)
        if strategy_class:
            return strategy_class(config)
        
        raise ValueError(f"Strategy {name} not found. Available: {list(cls._strategies.keys())}")
