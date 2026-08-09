"""Compatibility facade for the pre-v0.4 application import surface.

New code should import the focused service modules.  Keeping these re-exports
avoids breaking the existing `/v2` router and external local scripts while the
application boundary remains explicit.
"""

from worldstate.application.analysis_orchestrator import (
    CODE_VERSION,
    METHODOLOGY_VERSION,
    analyze_release,
    bootstrap_research_data,
    get_current_regime,
    get_provider_runs,
    get_quality_overview,
    get_release_detail,
    get_release_historical,
    get_release_timeline,
    get_release_windows,
    list_releases,
)
from worldstate.application.analysis_persistence import (
    diff_analysis_runs,
    get_analysis_manifest,
    replay_analysis_run,
)
from worldstate.application.consensus_service import append_consensus
from worldstate.application.evidence_service import get_evidence_pack
from worldstate.application.market_import_service import import_market_csv
from worldstate.application.release_commands import create_manual_release
from worldstate.application.report_service import get_release_explanations

__all__ = [
    "CODE_VERSION",
    "METHODOLOGY_VERSION",
    "analyze_release",
    "append_consensus",
    "bootstrap_research_data",
    "create_manual_release",
    "diff_analysis_runs",
    "get_analysis_manifest",
    "get_current_regime",
    "get_evidence_pack",
    "get_provider_runs",
    "get_quality_overview",
    "get_release_detail",
    "get_release_explanations",
    "get_release_historical",
    "get_release_timeline",
    "get_release_windows",
    "import_market_csv",
    "list_releases",
    "replay_analysis_run",
]
