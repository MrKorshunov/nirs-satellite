# Validation report: configurable simulation duration and Vizard cadence

**Checked:** 2026-11-06. **Branch:** feature/simulation-run-control. **Evidence:** [GitHub Actions run #42261308430](https://github.com/MrKorshunov/nirs-satellite/actions/runs/42261308430). Full execution tests used Basilisk 2.12.2 and Python 3.13.

## Real execution checks

| Environment | Scenario | Result |
|---|---|---|
| Ubuntu | 24 h physics, physics step 10 s, recording every 30 s, no Vizard | PASS: 2881 recorded points, 3 sampled access windows, independent geometry PASS, inputs_and_metrics.json and EXPLAIN_RESULTS.md created |
| Ubuntu | 3 h physics, physics step 10 s, recorder & Vizard every 30 s | PASS: 361 recorded points, Vizard ground marker recorded, 117148-byte .bin file, geometry PASS |
| Windows | 2 h physics, physics step 10 s, recorder & Vizard every 30 s | PASS: 241 recorded points, 1 sampled access window, geometry PASS, .bin exists and metadata saved |
| Windows | Original 1 orbit / Ground 01 + Payload 01 / previous Vizard behavior | PASS: 568 points on default orbit run, one synthetic 1000000-byte product, ground marker playback file produced |
| Python-only tests | CLI duration, modes, cadence multiples, large-run limits, erroneous Payload 01 combination | PASS |

**Important:** CI checks that playback .bin files are nonempty and contain the relevant target marker. Final appearance in Vizard remains for the user to verify after pulling this branch.

## What these numbers show

The 24-hour run has 2881 points because 86400 model seconds with one saved point every 30 seconds gives (86400 / 30) + 1. This is **not** the number of physics integration steps; those run every 10 seconds.

The 3-hour playback sample count similarly is (10800 / 30) + 1 = 361. A Vizard frame is recorded every 30 seconds, while the same underlying spacecraft dynamics still integrate every 10 seconds.

The number of access windows depends on the synthetic orbit, Earth rotation, ground point and time interval. Changing the sampling period alters the precision of the detected entry/exit times. It must not be interpreted as changing the underlying orbit.

## What is not yet checked

- **Live Streaming with connected Vizard on user's Windows.** The code follows Basilisk's official scenarioBasicOrbitStream.py pattern (liveStream=True; ClockSynch acceleration factor), but GitHub CI cannot provide a real interactive Vizard connection.
- Whether the user's Vizard build displays 2-hour and 24-hour playback exactly as intended; a generated .bin does not prove on-screen rendering.
- Numerical convergence for integration step sizes other than the baseline tested 10 s / 5 s pair. The current demonstrations vary recording or visualization cadence, NOT physical accuracy.
- Physical validity of multi-day orbits for a real satellite: J2, drag, real epoch and orientation are not included.
- Continuous payload generation. Existing Payload 01 deliberately remains a **single synthetic product** on the default one-orbit experiment. The runtime rejects long-run combinations with it.

## Outcome

The **offline batch and precomputed Vizard playback features** are ready for user-side tests. The **live mode is experimental** until explicitly checked with a connected Vizard. Scientific modeling proceeds with one KA; no constellation claims follow from these checks.
