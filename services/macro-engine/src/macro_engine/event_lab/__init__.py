"""Macro-event research calculations owned by WorldState."""

from macro_engine.event_lab.surprise import calculate_bundle_surprise
from macro_engine.event_lab.windows import calculate_event_windows, detect_earliest_reaction

__all__ = [
    "calculate_bundle_surprise",
    "calculate_event_windows",
    "detect_earliest_reaction",
]
