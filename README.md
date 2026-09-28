# spot-gpu-autoscaler

Rent **cheap on-demand GPUs** across providers (interruptible/spot support
planned), scale them up when work is pending and down when they go idle, hold a
**hard $/hr spend cap**, and run an **out-of-band reaper** that destroys
dead-but-still-billing instances *even when your app is down or you are locked
out of the box*.

> **On-demand today, spot next.** The Vast adapter currently rents *on-demand*
> instances. Interruptible/bid ("spot") rentals are on the roadmap; the cost cap
> and the out-of-band reaper — the real point of this project — work identically
> either way.

Zero runtime dependencies (Python standard library only). Bring your own provider
API key via an environment variable, plug in a state backend, and it works.

```bash
export VAST_API_KEY=...            # your provider key
pip install -e .
spotscale status                   # what is running and what it costs
spotscale reap --once              # kill exited/offline orphans right now
spotscale autoscale --demand 25 --once   # scale one tick toward a demand of 25 (drop --once to run the loop)
```

## Why this exists (a guardrail born from a real bill)

Spot GPUs are cheap until they aren't. The failure mode that pays for this whole
project is boring and brutal:

- Your in-app teardown has a bug, or the app crashes, or you get locked out of the
  host that runs it.
- Instances that have **exited** or gone **offline** keep **billing** — a stopped
  container still holds a rented machine.
- With nothing watching *from the outside*, orphans pile up quietly for days and
  the invoice is the first time anyone notices.

The lesson: **the thing that stops the bleeding must not depend on the thing that
sprang the leak.** So the reaper here talks straight to the provider API from
wherever you run it — a laptop, a cron box, a function — and kills anything in a
terminal-but-billable state within minutes. It needs no database, no app, and no
access to the machine that provisioned the instances. That independence is the
point; if the reaper needed the app to be healthy, it would be useless in exactly
the moment you need it.

## The three loops

**AutoScaler** — matches capacity to demand.
- Scales up when a pending-work signal appears and when the queue grows past a
  per-worker threshold, up to `max_workers`.
- Scales down idle workers after an idle grace period, never below `min_workers`.
- Reaps *stale* workers (heartbeat gone quiet) and workers *stuck starting*
  (never reported in), returning their state cleanly.

**CostGuard** — a hard ceiling on `$/hr`, enforced two ways.
- *Refuses* to provision when the next instance would push live spend over the cap.
- *Kills over-cap* as a backstop: if live spend is already above the ceiling
  (drift, a manual launch, a provider price change), it destroys the freshest
  instances first until spend is back under the line.

**Reaper** — the out-of-band safety net described above. Kills only instances in a
terminal-but-billable state (`exited`, `offline`), so it can never touch a
healthy running worker.

Run them together in one process, or run each on its own schedule. The reaper in
particular is best run somewhere *other* than your main app host.

## Architecture

```
        pending-work signal
                │
                ▼
          ┌───────────┐        ┌─────────────┐
          │ AutoScaler │──────▶│  CostGuard  │  refuse / kill over cap
          └───────────┘        └─────────────┘
                │                     │
                ▼                     ▼
          ┌──────────────────────────────┐
          │        Provider (spin/list/kill)  │  vast · memory · your own
          └──────────────────────────────┘
                │
                ▼
          ┌───────────┐
          │   State    │  json · sqlite · your own
          └───────────┘

   Reaper ──▶ Provider.list() ──▶ kill(exited/offline)   (no State, no app)
```

- **Provider** is an interface with exactly three methods: `spin(gpu, max_price)`,
  `list()`, `kill(id)`. A `VastProvider` (Vast.ai) and an in-memory `MemoryProvider`
  ship in the box. Write your own by subclassing `spotscale.providers.base.Provider`.
- **State** tracks the workers *you* provisioned (heartbeats, idle timers, cost).
  JSON and SQLite adapters ship. Write your own by subclassing
  `spotscale.state.base.StateBackend`.

## Quickstart with no provider account

The `memory` provider simulates a fleet so you can see the loops work before wiring
a real key:

```bash
SPOTSCALE_PROVIDER=memory spotscale autoscale --demand 40 --once
SPOTSCALE_PROVIDER=memory spotscale status
```

> **Note:** the `memory` fleet lives only inside a single process. The two
> commands above run in *separate* processes, so `status` sees an empty fleet —
> that's expected. To watch the memory fleet actually change, drive it from one
> process (e.g. a short Python script that spins a `MemoryProvider`, runs a tick,
> then prints `status`), or use a persistent `SPOTSCALE_PROVIDER=vast` fleet.

## Configuration (env vars, prefix `SPOTSCALE_`)

All values have sane defaults — treat them as *starting points* and tune to your
workload, not gospel.

- `SPOTSCALE_PROVIDER` — `vast` or `memory` (default `vast`).
- `SPOTSCALE_STATE` — `json` or `sqlite` (default `json`).
- `SPOTSCALE_STATE_PATH` — where state is persisted.
- `SPOTSCALE_GPU` — GPU model to request, e.g. `RTX_3090`.
- `SPOTSCALE_MAX_PRICE` — max `$/hr` for a *single* instance the scaler will spin.
- `SPOTSCALE_MAX_SPEND` — hard fleet-wide `$/hr` ceiling (the CostGuard cap).
- `SPOTSCALE_MIN_WORKERS` / `SPOTSCALE_MAX_WORKERS` — fleet size bounds.
- `SPOTSCALE_SCALE_THRESHOLD` — pending items per worker before scaling up.
- `SPOTSCALE_IDLE_TEARDOWN_S` — idle grace before a worker is torn down.
- `SPOTSCALE_STALE_HEARTBEAT_S` — heartbeat age that marks a worker dead.
- `SPOTSCALE_STARTING_TIMEOUT_S` — how long a worker may sit "starting" before it's failed.
- `SPOTSCALE_REAPER_ALERT_THRESHOLD` — reaping this many in one pass fires the alert
  hook (a sign your in-app teardown is still leaking).
- `SPOTSCALE_WORKER_IMAGE` — container image the provider launches (provider-specific).

Provider credentials are read from the provider's own env var
(`VAST_API_KEY` for Vast.ai) and are never written to disk, logs, or argv.

## Wiring a heartbeat

Your workers tell the scaler they're alive and whether they're busy:

```python
scaler.report_heartbeat(worker_id, busy=True)   # working a job
scaler.report_heartbeat(worker_id, busy=False)  # idle; starts the idle timer
```

A worker that stops reporting for `STALE_HEARTBEAT_S` is treated as dead, killed,
and removed — no orphan, no mystery line item.

## Extending

Providers and state backends are the two seams meant to be replaced:

```python
from spotscale.providers.base import Provider
from spotscale.models import Instance

class MyCloud(Provider):
    name = "mycloud"
    def spin(self, gpu, max_price, label=""): ...
    def list(self): ...            # -> list[Instance]
    def kill(self, instance_id): ...  # -> bool
```

## Tests

```bash
pip install -e ".[test]"
python -m pytest
```
