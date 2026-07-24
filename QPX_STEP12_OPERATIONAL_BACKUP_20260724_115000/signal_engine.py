"""
QPX Alpha Quant Research Platform
Step 9 Signal Engine

Purpose:
- Convert Step 8 feature outputs into trading signals
- Provide validated signal schema
- Maintain compatibility with feature_engine layer

Protected layers:
- importer pipeline
- CSV pipeline
- database lifecycle
- query layer
- analytics foundation
- Step 8 feature engine
"""

from datetime import datetime


class SignalEngine:
    """
    Step 9 signal generation engine
    """

    def __init__(self, threshold=0.0):
        self.threshold = threshold

    def generate_signal(self, features):
        """
        Generate a signal from feature data.

        Expected input:
            dict-like feature output

        Returns:
            dict signal schema
        """

        if features is None:
            raise ValueError("Feature input unavailable")

        score = self._calculate_score(features)

        if score > self.threshold:
            signal = "BUY"
        elif score < -self.threshold:
            signal = "SELL"
        else:
            signal = "HOLD"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "signal": signal,
            "score": score,
            "confidence": self._confidence(score),
            "source": "QPX_STEP_9_SIGNAL_ENGINE"
        }

    def _calculate_score(self, features):
        """
        Converts feature values into signal score.
        """

        if hasattr(features, "to_dict"):
            features = features.to_dict()

        numeric_values = []

        for value in features.values():
            if isinstance(value, (int, float)):
                numeric_values.append(value)

        if not numeric_values:
            return 0.0

        return sum(numeric_values) / len(numeric_values)

    def _confidence(self, score):
        """
        Basic confidence calculation.
        """

        confidence = min(abs(score), 1.0)

        return round(confidence, 4)


def generate_signal(features):
    """
    Functional interface for validation scripts.
    """

    engine = SignalEngine()
    return engine.generate_signal(features)


def validate_signal_schema(signal):
    """
    Validate Step 9 signal output format.
    """

    required_fields = [
        "timestamp",
        "signal",
        "score",
        "confidence",
        "source"
    ]

    if not isinstance(signal, dict):
        return False

    for field in required_fields:
        if field not in signal:
            return False

    return True


# Compatibility aliases
SignalGenerator = SignalEngine


if __name__ == "__main__":

    test_features = {
        "momentum": 0.5,
        "trend": 0.2,
        "volatility": -0.1
    }

    output = generate_signal(test_features)

    print("Signal Output:")
    print(output)

    print("Schema Valid:")
    print(validate_signal_schema(output))
