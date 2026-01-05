
import ta
print(f"TA Version: {ta.__version__}")
try:
    from ta.momentum import rsi
    print("ta.momentum.rsi FOUND")
except ImportError:
    print("ta.momentum.rsi NOT FOUND")

try:
    from ta.trend import rsi
    print("ta.trend.rsi FOUND")
except ImportError:
    print("ta.trend.rsi NOT FOUND")
except AttributeError:
    print("ta.trend.rsi ATTRIBUTE ERROR")
