# Voided records

Measurement records that are invalid but kept as evidence. **Do not plot these
or include them in any trend.** They have been removed from
`../j1_history.csv`.

Kept rather than deleted because the *way* they failed is itself a finding, and
because the guard that prevents a repeat (below) should be testable against real
bad data.

---

## 2026-10-18 — three `cycle` runs truncated by an unknown velocity cap

| File | `vel_limit` commanded | logged `backlash_deg` | true value |
|---|---|---|---|
| `20261018-145931_j1_cycle.json` | 1.0 rev/s | 30.11° | invalid |
| `20261018-145937_j1_cycle.json` | 1.5 rev/s | 77.51° | invalid |
| `20261018-145943_j1_cycle.json` | 2.0 rev/s | 108.42° | invalid |

J1's backlash is approximately **0.23°**, so these are off by two to three
orders of magnitude.

### What happened

`servo.max_velocity = 0.5` is a firmware cap on the board — absent from
`PROFILE` in `host/joint_setup_v2.py`, so nobody knew it existed. Commanding
`vel_limit` above 0.5 rev/s had no effect; `status` read `vel = +0.5003` and
`+0.4991`, pinned exactly at the cap.

`travel_time()` (`host/joint_console_v2.py:454`) computes the dwell from the
*commanded* limit, which the firmware ignored. So `do_cycle` sampled the joint
mid-flight and interpreted the incomplete travel as a position bias, which it
then reported as backlash:

```
vel_limit 2.0 -> actual 0.5:  true motion 1.83 s vs dwell 1.33 s
                              short by 0.50 s
0.50 s x 0.5 rev/s = 0.25 rev   vs  0.267 rev observed error
```

The shortfall predicts the error almost exactly.

### Why this is the serious kind of bug

`do_cycle` **did** print a warning — *"mean landing is far off... Either the
dwell is too short for this distance, or the joint is hitting something"* — and
then logged `backlash_deg` anyway, into the same history CSV as real
measurements. A test that warns but cannot fail is worse than one that crashes,
because the bad number survives into analysis.

### The run that is still valid

`20261018-145924_j1_cycle.json` (`vel_limit` 0.5, at the cap) completed properly
and remains in `j1_history.csv`: backlash 0.75°, spreads 0.30° / 0.01°. Only 2
round trips, so it carries little weight, but it is real.

### Guards that should exist before the next cycle run

1. Host reads `servo.max_velocity` at startup and clamps `vel_limit` to it with
   a warning.
2. `travel_time()` uses the *effective* limit, not the commanded one.
3. `do_cycle` and `do_random` refuse to emit metrics when the mean landing error
   exceeds a few percent of commanded travel.
4. `log_run` captures the full board config, so a limit that was in force is
   always recorded alongside the data.

See `docs/J1_CHARACTERIZATION_PLAN.md` §15.11 and §16 for the full analysis.
