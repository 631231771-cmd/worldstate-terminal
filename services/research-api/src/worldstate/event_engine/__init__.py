"""Macro-event research calculations owned by WorldState."""

from worldstate.event_engine.surprise import calculate_bundle_surprise
from worldstate.event_engine.windows import calculate_event_windows, detect_earliest_reaction

__all__ = [
    "calculate_bundle_surprise",
    "calculate_event_windows",
    "detect_earliest_reaction",
]
