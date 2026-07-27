"""Read-only X research through the user's local Agent Reach configuration.

The adapter deliberately keeps browser-cookie credentials outside the application
process contract. Credentials are loaded only when a child ``twitter`` process is
started, are passed through that child's environment, and are never returned,
logged, cached, or placed in command-line arguments.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class XResearchAccount:
    """One bounded X timeline used as an input, not an authority."""

    handle: str
    label: str
    account_class: str
    research_role: str


DEFAULT_X_RESEARCH_ACCOUNTS: tuple[XResearchAccount, ...] = (
    XResearchAccount("federalreserve", "美联储", "official", "美国货币政策与数据"),
    XResearchAccount("ecb", "欧洲央行", "official", "欧洲利率、通胀与金融条件"),
    XResearchAccount("IMFNews", "国际货币基金组织", "institutional", "全球增长与政策框架"),
    XResearchAccount("USTreasury", "美国财政部", "official", "财政、国债供给与制裁"),
    XResearchAccount("EIAgov", "美国能源信息署", "official", "能源供需与库存"),
    XResearchAccount("BIS_org", "国际清算银行", "institutional", "全球金融条件与银行体系"),
    XResearchAccount("OECD", "OECD", "institutional", "全球增长与领先指标"),
    XResearchAccount("bankofengland", "英格兰银行", "official", "英国货币政策与金融稳定"),
    XResearchAccount("Bank_of_Japan_e", "日本银行", "official", "日本货币政策与日元"),
    XResearchAccount("LizAnnSonders", "Liz Ann Sonders", "researcher", "经济数据与市场内部结构"),
    XResearchAccount("elerianm", "Mohamed El-Erian", "practitioner", "宏观政策与市场定价"),
    XResearchAccount("TheStalwart", "Joe Weisenthal", "practitioner", "市场叙事与实时线索"),
)

_CACHE_LOCK = asyncio.Lock()
_CACHE_KEY: tuple[object, ...] | None = None
_CACHE_AT = 0.0
_CACHE_ROWS: list[dict[str, object]] = []
_CACHE_STATUS: dict[str, object] = {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _default_config_path() -> Path:
    return Path.home() / ".agent-reach" / "config.yaml"


def _twitter_candidates(explicit: Path | None) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    discovered = shutil.which("twitter")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend(
        (
            Path.home() / ".local" / "bin" / "twitter.exe",
            Path.home() / ".local" / "bin" / "twitter",
        )
    )
    return tuple(dict.fromkeys(candidates))


def _resolve_twitter_executable(explicit: Path | None = None) -> Path | None:
    for candidate in _twitter_candidates(explicit):
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved.is_file():
            return resolved
    return None


def _find_cookie_credentials(node: object) -> dict[str, str]:
    """Find only the two documented Twitter credential fields in parsed YAML."""

    found: dict[str, str] = {}

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key).lower()
                if key in {"auth_token", "twitter_auth_token"} and isinstance(child, str):
                    found["TWITTER_AUTH_TOKEN"] = child
                elif key in {"ct0", "twitter_ct0"} and isinstance(child, str):
                    found["TWITTER_CT0"] = child
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    if not all(found.get(key) for key in ("TWITTER_AUTH_TOKEN", "TWITTER_CT0")):
        return {}
    return found


def load_agent_reach_credentials(config_path: Path) -> dict[str, str]:
    """Load credentials from one explicit local file without exposing its values."""

    try:
        resolved = config_path.expanduser().resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > 128 * 1024:
            return {}
        payload = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except (OSError, RuntimeError, UnicodeError, yaml.YAMLError):
        return {}
    return _find_cookie_credentials(payload)


def _engagement(metrics: object) -> int:
    if not isinstance(metrics, dict):
        return 0
    return sum(
        int(metrics.get(key) or 0)
        for key in ("likes", "retweets", "replies", "quotes", "bookmarks")
        if isinstance(metrics.get(key), (int, float))
    )


def parse_twitter_cli_payload(
    payload: object,
    account: XResearchAccount,
) -> list[dict[str, object]]:
    """Normalize the stable twitter-cli JSON envelope into research perspectives."""

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    rows: list[dict[str, object]] = []
    for post in data:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("id") or "").strip()
        text = " ".join(str(post.get("text") or "").split())
        author = post.get("author")
        author_row = author if isinstance(author, dict) else {}
        handle = str(author_row.get("screenName") or account.handle).lstrip("@")
        if not post_id or not text or not handle:
            continue
        metrics = post.get("metrics")
        engagement = _engagement(metrics)
        rows.append(
            {
                "id": f"agent-reach-x-{post_id}",
                "title": text[:280],
                "summary": text[:900],
                "source": f"X · @{handle}",
                "author": str(author_row.get("name") or account.label),
                "url": f"https://x.com/{handle}/status/{post_id}",
                "published_at": post.get("createdAtISO") or post.get("createdAt"),
                "category": "perspective",
                "language": post.get("lang") or "en",
                "source_class": "social",
                "account_class": account.account_class,
                "research_role": account.research_role,
                "channel": "agent_reach_x",
                "importance": min(94, 58 + min(36, engagement // 20)),
                "engagement": engagement,
                "views": (
                    int(metrics.get("views") or 0)
                    if isinstance(metrics, dict) and isinstance(metrics.get("views"), (int, float))
                    else 0
                ),
            }
        )
    return rows


def _safe_call_result(
    account: XResearchAccount,
    *,
    status: str,
    items: int = 0,
    duration_ms: int = 0,
    latest_at: object = None,
    reason: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "handle": f"@{account.handle}",
        "label": account.label,
        "account_class": account.account_class,
        "research_role": account.research_role,
        "status": status,
        "items": items,
        "duration_ms": duration_ms,
        "latest_at": latest_at,
    }
    if reason:
        row["reason"] = reason
    return row


class AgentReachXProvider:
    """Fetch a small, cached set of X timelines using Agent Reach's local CLI."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        config_path: Path | None = None,
        executable_path: Path | None = None,
        accounts: tuple[XResearchAccount, ...] = DEFAULT_X_RESEARCH_ACCOUNTS,
        max_posts_per_account: int = 3,
        timeout_seconds: float = 14.0,
        cache_seconds: float = 20 * 60,
        concurrency: int = 3,
    ) -> None:
        self.enabled = enabled
        self.config_path = config_path or _default_config_path()
        self.executable_path = executable_path
        self.accounts = accounts
        self.max_posts_per_account = max(1, min(max_posts_per_account, 10))
        self.timeout_seconds = max(2.0, min(timeout_seconds, 30.0))
        self.cache_seconds = max(60.0, cache_seconds)
        self.concurrency = max(1, min(concurrency, 3))

    def _base_status(
        self,
        *,
        configured: bool,
        executable: bool,
    ) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "configured": configured,
            "connected": False,
            "backend": "agent_reach_twitter_cli",
            "mode": "local_cookie_read_only",
            "credential_storage": "local_config_to_child_process_only",
            "accounts": len(self.accounts),
            "calls_attempted": 0,
            "calls_succeeded": 0,
            "items": 0,
            "cache": {
                "hit": False,
                "ttl_seconds": int(self.cache_seconds),
                "fetched_at": None,
            },
            "executable_available": executable,
            "calls": [],
            "checked_at": _utc_now(),
        }

    async def _run_account(
        self,
        executable: Path,
        credentials: dict[str, str],
        account: XResearchAccount,
        semaphore: asyncio.Semaphore,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        started = monotonic()
        async with semaphore:
            child_environment = os.environ.copy()
            child_environment.update(credentials)
            child_environment.setdefault("PYTHONIOENCODING", "utf-8")
            try:
                process = await asyncio.create_subprocess_exec(
                    str(executable),
                    "user-posts",
                    account.handle,
                    "--max",
                    str(self.max_posts_per_account),
                    "--json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=child_environment,
                )
                stdout, _ = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError:
                if "process" in locals() and process.returncode is None:
                    process.kill()
                    await process.communicate()
                return [], _safe_call_result(
                    account,
                    status="timeout",
                    duration_ms=int((monotonic() - started) * 1000),
                    reason="bounded_timeout",
                )
            except OSError:
                return [], _safe_call_result(
                    account,
                    status="failed",
                    duration_ms=int((monotonic() - started) * 1000),
                    reason="process_unavailable",
                )
        duration_ms = int((monotonic() - started) * 1000)
        if process.returncode != 0 or len(stdout) > 2_000_000:
            return [], _safe_call_result(
                account,
                status="failed",
                duration_ms=duration_ms,
                reason="upstream_error",
            )
        try:
            payload: Any = json.loads(stdout.decode("utf-8", errors="replace"))
        except (UnicodeError, json.JSONDecodeError):
            return [], _safe_call_result(
                account,
                status="failed",
                duration_ms=duration_ms,
                reason="invalid_response",
            )
        rows = parse_twitter_cli_payload(payload, account)[: self.max_posts_per_account]
        latest_at = rows[0].get("published_at") if rows else None
        return rows, _safe_call_result(
            account,
            status="ok",
            items=len(rows),
            duration_ms=duration_ms,
            latest_at=latest_at,
        )

    async def fetch(
        self,
        *,
        fresh: bool = False,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        """Return public X rows plus a credential-free observability record."""

        global _CACHE_AT, _CACHE_KEY, _CACHE_ROWS, _CACHE_STATUS

        executable = _resolve_twitter_executable(self.executable_path)
        credentials = load_agent_reach_credentials(self.config_path) if self.enabled else {}
        status = self._base_status(
            configured=bool(credentials),
            executable=executable is not None,
        )
        if not self.enabled:
            status["state"] = "disabled"
            return [], status
        if executable is None:
            status["state"] = "cli_missing"
            return [], status
        if not credentials:
            status["state"] = "credentials_missing"
            return [], status

        cache_key = (
            str(executable),
            str(self.config_path.expanduser()),
            tuple(account.handle for account in self.accounts),
            self.max_posts_per_account,
        )
        async with _CACHE_LOCK:
            cache_age = monotonic() - _CACHE_AT
            if (
                not fresh
                and cache_key == _CACHE_KEY
                and _CACHE_STATUS
                and cache_age < self.cache_seconds
            ):
                cached_status = {**_CACHE_STATUS}
                cached_cache = _CACHE_STATUS.get("cache")
                cached_status["cache"] = {
                    **(cached_cache if isinstance(cached_cache, dict) else {}),
                    "hit": True,
                    "age_seconds": int(cache_age),
                }
                cached_status["checked_at"] = _utc_now()
                return [dict(row) for row in _CACHE_ROWS], cached_status

            semaphore = asyncio.Semaphore(self.concurrency)
            results = await asyncio.gather(
                *(
                    self._run_account(executable, credentials, account, semaphore)
                    for account in self.accounts
                )
            )
            rows = [row for account_rows, _call in results for row in account_rows]
            calls = [call for _account_rows, call in results]
            succeeded = sum(call["status"] == "ok" for call in calls)
            fetched_at = _utc_now()
            status.update(
                {
                    "state": "connected" if succeeded else "unavailable",
                    "connected": succeeded > 0,
                    "calls_attempted": len(calls),
                    "calls_succeeded": succeeded,
                    "items": len(rows),
                    "calls": calls,
                    "cache": {
                        "hit": False,
                        "ttl_seconds": int(self.cache_seconds),
                        "fetched_at": fetched_at,
                        "age_seconds": 0,
                    },
                    "checked_at": fetched_at,
                }
            )
            _CACHE_KEY = cache_key
            _CACHE_AT = monotonic()
            _CACHE_ROWS = [dict(row) for row in rows]
            _CACHE_STATUS = {**status}
            return rows, status


def reset_agent_reach_cache() -> None:
    """Clear module cache for deterministic tests."""

    global _CACHE_AT, _CACHE_KEY, _CACHE_ROWS, _CACHE_STATUS
    _CACHE_KEY = None
    _CACHE_AT = 0.0
    _CACHE_ROWS = []
    _CACHE_STATUS = {}
