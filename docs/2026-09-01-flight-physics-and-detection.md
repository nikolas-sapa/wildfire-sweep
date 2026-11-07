# Flight physics and thermal detection: does the airframe support the model?

> Historical analysis (August/September 2026). Retained for provenance; assumptions and numerical framing may predate the current research track. Start with the current [research overview](../README.md) and [captured anchor](../research_results/2026-11-07-anchor/summary.csv).

The cost model prices a DJI Matrice 4TD in a DJI Dock 3 across a spacing/drone
sweep, but nothing in `sweep.py` or `sensitivity.py` checks whether that
aircraft can actually fly the resulting missions, or what its sensor can see.
This doc closes both gaps. It does not touch `sweep.py`, `sensitivity.py`,
`suppression.py`, or existing docs — the flyability numbers below are already
computed and checked in `sensitivity.py`'s Analysis 1
(`mission_geometry`, `mission_time`, `flyability_verdict`); this doc explains
what those numbers mean and adds a detection-range analysis that has no code
counterpart yet.

## 1. Aircraft and dock specs (cited)

**DJI Matrice 4TD / Matrice 4T family** (published):
- Max flight time: 46–49 min
- Max horizontal speed: 21 m/s
- Max wind resistance (takeoff, landing, operation): 12 m/s
- Operating temperature: −30 to 50 °C
- MTOM: ~2090 g

**DJI Dock 3** (published):
- Minimum interval between sorties: 27 min (15%→95% charge, 25 °C, single
  aircraft, no hot-swap)
- IP56
- Rated to 50 °C

Two things worth flagging up front, one favourable and one not.

The MTOM is a genuine positive: at ~2.1 kg the Matrice 4TD sits well under
both the 4 kg and 25 kg EASA thresholds, which is favourable for SORA
ground-risk class — smaller crash energy, lighter regulatory category.

The contrast worth knowing about: Microavia's Spanish drone-in-a-box
advertises a 2-minute autonomous battery swap against the Dock 3's 27-minute
recharge. That is an architectural difference in the docking system, not a
tuning knob on this one — swapping vendors would change the turnaround
assumption by an order of magnitude, not by adjusting `turnaround_s`.

## 2. Flight feasibility

The sweep model as built has **no endurance or range limit at all** — a
drone could fly arbitrarily far in the simulation and it would just take
however long it takes. Nothing in `dispatch` or `season_metrics` checks
whether a mission fits inside the aircraft's battery. Analysis 1 in
`sensitivity.py` is the missing check, run after the fact against the
existing frontier configs.

The second gap is `base_grid`: it floors `n = side_km // spacing_km` and
re-derives the actual spacing as `side_km / n`, so the `spacing_km` axis
label in `results.csv` is nominal, not the literal inter-base distance
(documented already at `sweep.py`, Task 2 note in the build log). Nominal
26 km is really 30.85 km between bases; nominal 16 km is really 20.57 km.
Every flyability number below uses the actual, re-derived spacing.

### Worst-case mission time by config, at 47.5 min cited endurance (midpoint)

| Nominal spacing | Bases | Worst mission | No reserve | 25% SORA reserve | Verdict |
|---|---|---|---|---|---|
| 26 km (4 bases) | 4 | 38.2 min | +19% margin | **−7% (IMPOSSIBLE)** | MARGINAL → fails with reserve |
| 16 km (headline, 9 bases) | 9 | 26.1 min | +45% margin | +27% margin | FEASIBLE |
| 12 km | 25 | 16.4 min | feasible | feasible | FEASIBLE |
| 8 km | 49 | 12.4 min | feasible | feasible | FEASIBLE |
| 5 km | 144 | 7.9 min | feasible | feasible | FEASIBLE |

Plainly: **the EUR 67/km²/yr cheap frontier point is not flyable under any
realistic reserve margin.** It was already withdrawn from the reported
frontier for failing the quality gate at 200 seasons (see the build log's
I-3 finding, 74–77% unserved at the cheap end). This is now a second,
independent reason it does not survive contact with reality — not a modeling
artifact this time, physics. There is no cheap end to this frontier.
EUR 101/km²/yr is the floor, not a recommendation to push cheaper.

### What the headline is load-bearing on

**Cruise speed.** The model's `cruise_mps` default is 20 m/s, which is 95%
of the cited 21 m/s max horizontal speed — not a sustainable cruise figure
with any margin. `sweep.py`'s comment claims this "absorbs wind derating";
the spec it is drawn from contradicts that claim directly, since 20 m/s
leaves almost no headroom below the airframe's hard ceiling. Sweeping
`cruise_mps` on the headline (16 km/9-base) config:

- 18 m/s: still holds (headline intact)
- 15 m/s: misses the 15-minute p90 threshold; miss rate triples
- 12 m/s (also the cited max wind resistance — this is not a pessimistic
  tail, it is the realistic operating ceiling in a meltemi wind): p90 hits
  16.5 min, 19.9% of fires missed

So the headline's speed margin is thin and its failure mode is exactly the
wind condition the airframe is rated for, not some worse edge case.

**Turnaround — not load-bearing, in either direction.** Tested at the real
Dock 3 cited figure (1620 s) and at a 2400 s heat-derated estimate for Greek
summer, headline p90 moves from 10.08 to 10.14 min. Fleet utilisation sits
near 0.5% at this ignition density, so a base is essentially never mid-charge
when the next alert lands — there's no contention to expose. The model's
original `turnaround_s` default (600 s) was wrong by 2.7x against the cited
spec, but in a direction that does not move the metric at Attica's ignition
density. Worth knowing, not worth fixing under time pressure.

## 3. Thermal detection range

This section answers a question the flyability check doesn't: could the
drone detect a fire from standoff, without flying all the way to the
coordinates? If yes, that changes network design — you'd credit a detection
radius and could space bases further apart. If no, "fly to the coordinates"
is the accurate description of the mission, not a simplification.

### Sensor geometry (computed from published specs, worked shown)

Matrice 4T thermal payload: 640×512 array, 12 µm pixel pitch, 45° diagonal
field of view, NETD ≤ 50 mK (enterprise.dji.com/matrice-4-series/specs).

- Sensor diagonal: `sqrt((640×12µm)² + (512×12µm)²)` = 9.83 mm
- Solve `45° = 2·atan(diag / 2f)` for f: **f ≈ 11.9 mm** — the real physical
  focal length.
- **DJI's published "53 mm" is a 35mm-equivalent marketing figure, not the
  physical focal length.** Using 53 mm in the IFOV calculation would overstate
  detection range by roughly 4x. Flagging this explicitly because it's the
  easiest place to get this analysis wrong by a large factor.
- IFOV = 12 µm / 11.9 mm ≈ **1.01 mrad** — consistent with typical uncooled
  12 µm 640×512 cores in the field.
- Ground sample distance at slant range R: **GSD ≈ 1.01×10⁻³ · R**.
- **The 28x zoom is digital** (crop + interpolate): it changes framing, not
  resolving power. It buys no additional range.

### Pixel-filling detection range

Range at which a fire fills at least one GSD, with contrast of hundreds of K
over ambient — far above the 50 mK noise floor, so detection at this range is
not marginal:

| Fire size | Pixel-filling range |
|---|---|
| 1 m² ignition | ~990 m |
| 10 m² fire | ~3.13 km |
| 100 m² fire | ~9.9 km |

### The sub-pixel regime — and why it doesn't rescue long range

Satellite fire products (Dozier 1981 bispectral method, used for MODIS and
AVHRR) get their sub-pixel leverage from a mid-wave infrared channel near
4 µm, where Planck-law sensitivity to hot targets is far steeper than in
LWIR. The Matrice's payload is a broadband LWIR-only uncooled bolometer with
no such channel — its sub-pixel hot-target sensitivity is materially weaker
than the satellite literature implies, and that literature does not
transfer directly.

A smouldering ignition is also a 400–600 °C surface, not the 800–1200 K
flame that makes sub-pixel detection easy from orbit. Confident detection
wants apparent pixel ΔT several times NETD — roughly 150–250 mK — to clear
clutter. Net: sub-pixel gain is perhaps 1.5x–3x beyond pixel-filling range
for a hot flaming fire, and much less for smouldering. A modest bonus, not a
step change. No validated published figure pins this down for uncooled LWIR
at operational UAS altitudes — say so plainly rather than inventing a number.

### Atmosphere

LWIR suffers far less Mie scattering than visible or NIR, so it sees through
thin-to-moderate smoke that would white out an RGB camera. Not immune,
though: water vapour and CO2 absorption plus dense wet smoke still
attenuate, roughly 5–15%/km in humid clear air, potentially 30–50%/km or
worse in thick smoke or fog. All ranges above are clear-to-hazy-air upper
bounds.

### Field practice corroborates the arithmetic

Published UAS wildfire thermal work — FLAME3 (arxiv.org/pdf/2412.02831), the
USFS RGB/IR dataset (research.fs.usda.gov/treesearch/67004), HIT-UAV
(PMC10119175) — flies at 60–120 m AGL, essentially overhead. None of these
report validated multi-km detection of a sub-100 m² fire from an airborne
platform. That's a field-practice signal, not a proven sensitivity ceiling,
but it sits at the same order of magnitude as the optics calculation above.

### The Pano AI reconciliation

Worth addressing directly because the published number looks contradictory
at first glance. Pano's 10–30+ mile detection figures are **visible-spectrum
smoke plume detection from a fixed tower**, not point-source thermal
detection of a new ignition. A developed plume is tens to hundreds of metres
across, rising, high-contrast against clean sky — a later stage of the fire,
detected with a different sensor modality, against a target orders of
magnitude larger than a new ignition. It does not transfer to this problem.

Design implication, stated plainly: a fixed camera on a hill, or a satellite
doing plume detection, is the right tool for **finding** a fire. An airborne
thermal camera is the right tool for **confirming and mapping** one once
pointed at roughly the right coordinates.

### Geolocation at range

Even a favourable 0.2° combined pointing/attitude/gimbal error gives lateral
error of `R·tan(0.2°)`: roughly 10 m at 3 km, 28 m at 8 km — before terrain
elevation uncertainty, which dominates at shallow grazing angles. Good enough
to cue a response. Not good enough to hand a commander a usable perimeter.
Perimeter mapping needs the drone to close distance and fly a near-nadir
pattern at sub-metre GSD — so even if standoff detection worked, the drone
still has to close in to do the job the metric actually cares about.

## 4. What this means for the model

**Recommendation: do not credit a detection radius in `sweep.py`.** For a
new ignition — the size regime that matters for a first-alert system —
pixel-filling range is ~990 m against a 14.5 km worst-case leg in the 9-base
configuration. "Fly to the coordinates" is an accurate model of the mission,
not a simplification that could be relaxed. Where a radius genuinely exists
(a 10–100 m² fire, several hundred metres to a few km of range) it doesn't
help the metric: a fire that size is no longer new, and the time budget has
already been consumed by fire growth, not flight. Crediting range there
would flatter the model on the wrong end of the curve — it would look like
a win but represent a fire that's already escalated.

**The architectural conclusion — the part worth keeping.** Since detecting a
genuinely new ignition needs either overhead flight or roughly 1 km
standoff, thermal is not viable as the first-alert mechanism. The
architecture already treats the drone as alert-driven (dispatched to a
coordinate from an external trigger) rather than as the discovery sensor.
**This finding validates the design rather than challenging it** — the
division of labour (fixed/satellite detection → drone dispatch → thermal
confirmation and mapping) is correct, and `time-to-eyes-on-fire` is
measuring the right thing: arrival, confirmation, and mapping, which
genuinely requires flying to the coordinates rather than loitering at
standoff.

**Caveat, stated honestly:** the detection-range figures in section 3 are an
engineering estimate computed from published optics and cross-checked
against literature, not a validated field measurement. Treat them
accordingly — good enough to settle the architectural question (thermal is
not a first-alert sensor at any plausible number in this range), not good
enough to be quoted as a spec.
