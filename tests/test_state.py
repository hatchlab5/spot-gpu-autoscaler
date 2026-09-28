from spotscale.models import InstanceStatus, WorkerRecord
import pytest


def _rec(wid, status=InstanceStatus.RUNNING.value, cost=0.30, started=1000.0):
    return WorkerRecord(
        worker_id=wid,
        provider="memory",
        instance_id=f"inst-{wid}",
        status=status,
        gpu="RTX_3090",
        hourly_cost=cost,
        started_at=started,
    )


def test_add_get_roundtrip(state):
    state.add(_rec("w1"))
    got = state.get("w1")
    assert got is not None
    assert got.worker_id == "w1"
    assert got.instance_id == "inst-w1"
    assert got.hourly_cost == 0.30


def test_get_missing_returns_none(state):
    assert state.get("nope") is None


def test_update_whitelisted(state):
    state.add(_rec("w1"))
    state.update("w1", status=InstanceStatus.IDLE.value, idle_since=1234.0)
    got = state.get("w1")
    assert got.status == InstanceStatus.IDLE.value
    assert got.idle_since == 1234.0


def test_update_rejects_unknown_field(state):
    state.add(_rec("w1"))
    with pytest.raises(KeyError):
        state.update("w1", started_at=999.0)


def test_remove(state):
    state.add(_rec("w1"))
    state.remove("w1")
    assert state.get("w1") is None


def test_list_by_status(state):
    state.add(_rec("w1", status=InstanceStatus.RUNNING.value))
    state.add(_rec("w2", status=InstanceStatus.IDLE.value))
    state.add(_rec("w3", status=InstanceStatus.STOPPED.value))
    active = state.list((InstanceStatus.RUNNING, InstanceStatus.IDLE))
    assert {r.worker_id for r in active} == {"w1", "w2"}


def test_total_hourly_cost_active_only(state):
    state.add(_rec("w1", status=InstanceStatus.RUNNING.value, cost=0.30))
    state.add(_rec("w2", status=InstanceStatus.IDLE.value, cost=0.25))
    state.add(_rec("w3", status=InstanceStatus.STOPPED.value, cost=9.99))
    assert state.total_hourly_cost() == 0.55

