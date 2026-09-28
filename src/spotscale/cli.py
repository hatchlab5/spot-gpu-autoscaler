"""Command-line entry point: status | autoscale | reap | costguard."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Callable

from .autoscaler import AutoScaler, run_loop as autoscale_loop
from .config import Config
from .costguard import CostGuard, run_loop as costguard_loop
from .providers import get_provider
from .providers.base import ProviderError
from .reaper import Reaper, run_loop as reaper_loop
from .state import get_state


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _build_provider(config: Config):
    name = os.environ.get("SPOTSCALE_PROVIDER", "vast")
    return get_provider(name, config=config)


def _build_state():
    kind = os.environ.get("SPOTSCALE_STATE", "json")
    path = os.environ.get("SPOTSCALE_STATE_PATH")
    return get_state(kind, path)


def _demand_fn(args) -> Callable[[], int]:
    """Resolve the pending-work signal from --demand or --demand-file."""
    if args.demand_file:
        def read_file():
            try:
                with open(args.demand_file) as f:
                    return int((f.read().strip() or "0"))
            except (OSError, ValueError):
                return 0
        return read_file
    fixed = int(args.demand)
    return lambda: fixed


# ---------------------------------------------------------------------- #
def cmd_status(args) -> int:
    config = Config.from_env()
    provider = _build_provider(config)
    try:
        instances = provider.list()
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    total = round(sum(i.price_per_hour for i in instances), 4)
    print(f"provider: {provider.name}")
    print(f"instances: {len(instances)}")
    for i in instances:
        print(
            f"  - {i.id}  {i.status:<9}  {i.gpu:<14}  ${i.price_per_hour:.4f}/hr  "
            f"up {i.uptime_hours}h  {i.label}"
        )
    print(f"live spend: ${total:.4f}/hr  (~${total * 24:.2f}/day)")
    print(f"cap: ${config.max_hourly_spend:.4f}/hr")
    if total > config.max_hourly_spend:
        print("  ** OVER CAP **")
    return 0


def cmd_autoscale(args) -> int:
    config = Config.from_env()
    provider = _build_provider(config)
    state = _build_state()
    guard = CostGuard(provider, config.max_hourly_spend)
    scaler = AutoScaler(provider, state, config, _demand_fn(args), cost_guard=guard)
    if args.once:
        scaler.tick(dry_run=args.dry_run)
    else:
        autoscale_loop(scaler, config.scale_interval_s, dry_run=args.dry_run)
    return 0


def cmd_reap(args) -> int:
    config = Config.from_env()
    provider = _build_provider(config)
    reaper = Reaper(provider, alert_threshold=config.reaper_alert_threshold)
    if args.once:
        killed = reaper.reap(dry_run=args.dry_run)
        print(f"reaped {len(killed)} orphan(s): {killed}")
    else:
        reaper_loop(reaper, config.reaper_interval_s, dry_run=args.dry_run)
    return 0


def cmd_costguard(args) -> int:
    config = Config.from_env()
    provider = _build_provider(config)
    guard = CostGuard(provider, config.max_hourly_spend)
    if args.once:
        killed = guard.enforce(dry_run=args.dry_run)
        print(f"live spend: ${guard.current_spend():.4f}/hr  cap: ${config.max_hourly_spend:.4f}/hr")
        print(f"killed {len(killed)} over-cap instance(s): {killed}")
    else:
        costguard_loop(guard, config.reaper_interval_s, dry_run=args.dry_run)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spotscale", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="show running instances and live spend")
    s.set_defaults(func=cmd_status)

    a = sub.add_parser("autoscale", help="scale toward a pending-work signal")
    a.add_argument("--demand", type=int, default=0, help="fixed pending-work count")
    a.add_argument("--demand-file", help="file containing the pending-work count")
    a.add_argument("--once", action="store_true", help="run one tick and exit")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_autoscale)

    r = sub.add_parser("reap", help="kill exited/offline orphan instances")
    r.add_argument("--once", action="store_true", help="run one pass and exit")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_reap)

    c = sub.add_parser("costguard", help="enforce the hard $/hr spend cap")
    c.add_argument("--once", action="store_true", help="run one pass and exit")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_costguard)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

