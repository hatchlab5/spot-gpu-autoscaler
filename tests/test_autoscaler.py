from spotscale.autoscaler import AutoScaler
from spotscale.costguard import CostGuard
from spotscale.models import ACTIVE_STATUSES, InstanceStatus
from spotscale.providers.memory import MemoryProvider


def _scaler(provider, state, config, clock, demand, cost_guard=None):
    return AutoScaler(
        provider,
        state,
        config,
        demand_fn=(demand if callable(demand) else (lambda: demand)),
        cost_guard=cost_guard,
        now_fn=clock,
    )


def test_scale_up_from_zero_on_demand(provider, state, config, clock):
    s = _scaler(provider, state, config, clock, demand=5)
    s.tick()
    assert len(state.list(ACTIVE_STATUSES)) == 1
    assert len(provider.list()) == 1


def test_no_scale_when_no_demand(provider, state, config, clock):
    s = _scaler(provider, state, config, clock, demand=0)
    s.tick()
    assert state.list(ACTIVE_STATUSES) == []


def test_scale_up_respects_threshold_and_max(provider, state, config, clock):
    # threshold=10, max_workers=3. High demand should add at most one per tick,
    # and never exceed max_workers.
    s = _scaler(provider, state, config, clock, demand=1000)
    for _ in range(10):
        s.tick()
        # heartbeat everything so nothing is reaped as stale between ticks
        for r in state.list(ACTIVE_STATUSES):
            s.report_heartbeat(r.worker_id, busy=True)
    assert len(state.list(ACTIVE_STATUSES)) == config.max_workers


def test_min_workers_floor(provider, state, config, clock):
    config.min_workers = 2
    s = _scaler(provider, state, config, clock, demand=0)
    s.tick()
    assert len(state.list(ACTIVE_STATUSES)) == 2


def test_scale_down_idle_after_grace(provider, state, config, clock):
    s = _scaler(provider, state, config, clock, demand=5)
    s.tick()
    wid = state.list(ACTIVE_STATUSES)[0].worker_id
    # worker reports idle, then demand disappears
    s.report_heartbeat(wid, busy=False)
    s.demand_fn = lambda: 0
    # not yet past idle grace
    clock.advance(config.idle_teardown_s - 10)
    s.report_heartbeat(wid, busy=False)  # keep heartbeat fresh, idle_since preserved
    s.tick()
    assert len(state.list(ACTIVE_STATUSES)) == 1
    # now past grace
    clock.advance(60)
    s.report_heartbeat(wid, busy=False)
    s.tick()
    assert state.get(wid).status == InstanceStatus.STOPPED.value
    assert provider.list() == []


def test_stale_worker_reaped(provider, state, config, clock):
    s = _scaler(provider, state, config, clock, demand=5)
    s.tick()
    wid = state.list(ACTIVE_STATUSES)[0].worker_id
    s.report_heartbeat(wid, busy=True)
    # heartbeat goes silent well past the stale threshold
    clock.advance(config.stale_heartbeat_s + 60)
    s.demand_fn = lambda: 0
    s.tick()
    assert state.get(wid).status == InstanceStatus.FAILED.value
    assert provider.list() == []


def test_stuck_starting_failed(provider, state, config, clock):
    # Provision but never heartbeat; worker stays 'starting'.
    s = _scaler(provider, state, config, clock, demand=5)
    s.tick()
    wid = state.list(ACTIVE_STATUSES)[0].worker_id
    assert state.get(wid).status == InstanceStatus.STARTING.value
    clock.advance(config.starting_timeout_s + 60)
    s.demand_fn = lambda: 0
    s.tick()
    assert state.get(wid).status == InstanceStatus.FAILED.value


def test_cost_cap_blocks_provision(provider, state, config, clock):
    # Pre-load provider with spend at the cap so the guard refuses.
    config.max_hourly_spend = 0.50
    existing = provider.spin("RTX_3090", 0.60)
    provider.set_price(existing.id, 0.50)  # live spend == cap
    guard = CostGuard(provider, config.max_hourly_spend)
    s = _scaler(provider, state, config, clock, demand=5, cost_guard=guard)
    s.tick()
    # no new worker provisioned
    assert state.list(ACTIVE_STATUSES) == []


def test_dry_run_provisions_nothing(provider, state, config, clock):
    s = _scaler(provider, state, config, clock, demand=5)
    s.tick(dry_run=True)
    assert state.all() == []
    assert provider.list() == []

