from spotscale.providers.memory import MemoryProvider
from spotscale.reaper import Reaper


def test_reaps_only_exited_and_offline():
    p = MemoryProvider()
    running = p.spin("RTX_3090", 0.60)
    exited = p.spin("RTX_3090", 0.60)
    offline = p.spin("RTX_3090", 0.60)
    p.set_status(exited.id, "exited")
    p.set_status(offline.id, "offline")

    reaper = Reaper(p)
    killed = set(reaper.reap())
    assert killed == {exited.id, offline.id}
    # the running instance survives
    remaining = {i.id for i in p.list()}
    assert remaining == {running.id}


def test_reap_clean_when_none_dead():
    p = MemoryProvider()
    p.spin("RTX_3090", 0.60)
    reaper = Reaper(p)
    assert reaper.reap() == []


def test_dry_run_kills_nothing():
    p = MemoryProvider()
    e = p.spin("RTX_3090", 0.60)
    p.set_status(e.id, "exited")
    reaper = Reaper(p)
    would = reaper.reap(dry_run=True)
    assert would == [e.id]
    assert len(p.list()) == 1


def test_alert_fires_over_threshold():
    p = MemoryProvider()
    ids = []
    for _ in range(3):
        inst = p.spin("RTX_3090", 0.60)
        p.set_status(inst.id, "exited")
        ids.append(inst.id)

    seen = {}

    def alert(count, killed):
        seen["count"] = count
        seen["killed"] = killed

    reaper = Reaper(p, alert_threshold=3, alert_fn=alert)
    reaper.reap()
    assert seen["count"] == 3
    assert set(seen["killed"]) == set(ids)


def test_alert_does_not_fire_under_threshold():
    p = MemoryProvider()
    inst = p.spin("RTX_3090", 0.60)
    p.set_status(inst.id, "exited")
    fired = {"v": False}
    reaper = Reaper(p, alert_threshold=5, alert_fn=lambda *_: fired.__setitem__("v", True))
    reaper.reap()
    assert fired["v"] is False


def test_label_prefix_scopes_reaping():
    p = MemoryProvider()
    mine = p.spin("RTX_3090", 0.60, label="spot-abc")
    theirs = p.spin("RTX_3090", 0.60, label="other-xyz")
    p.set_status(mine.id, "exited")
    p.set_status(theirs.id, "exited")
    reaper = Reaper(p, label_prefix="spot-")
    killed = reaper.reap()
    assert killed == [mine.id]
    assert {i.id for i in p.list()} == {theirs.id}

