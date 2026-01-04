
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
import pandas as pd

@dataclass
class StrategyResult:
    """Standardized output from any strategy calculation."""
    signal: Optional[str] = None  # 'BUY', 'SELL', or None
    indicators: Dict[str, Any] = field(default_factory=dict) # Key-Value pairs for logging (e.g., {'sma_50': 100.5})
    metadata: Dict[str, Any] = field(default_factory=dict) # Extra context for audit logs

class BaseStrategy:
    """Abstract base class for all trading strategies."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = "BaseStrategy"

    def calculate(self, df: pd.DataFrame) -> StrategyResult:
        """
        Process candle history and return a signal/indicators.
        Expected to populate 'indicators' even if signal is None, for visualization/logging.
        """
        raise NotImplementedError("Strategies must implement calculate method")
