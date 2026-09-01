# Research pass 3 — cost model grounding

Scope: replace the placeholder cost figures in `sweep.py`'s CONFIG with
sourced numbers, or explicit assumptions where nothing citable exists. Four
areas: unit economics, startup graveyard, Greek procurement/BVLOS, ignition
density and fire model. This is the source of truth for every number now in
CONFIG — do not re-derive them from memory later, come back here.

## What changed in CONFIG and why

| Param | Old | New | Basis |
| --- | --- | --- | --- |
| `drone_cost` | 15,000 | 21,500 | DJI Matrice 4TD list price ($23,409, 2026) |
| `base_cost` | 35,000 | 14,600 | DJI Dock 3 list price ($15,890, 2026), dock only |
| `install_cost` | 20,000 | 12,000 | proxy, not a drone-specific figure — see below |
| `maintenance_frac` | 0.15 | 0.25 | midpoint of the 20-30%/yr hardware maintenance rule of thumb |
| `hardware_life_yr` | 5.0 | 3.0 | assumption, supported — see below |
| `opex_per_base_yr` | — (didn't exist) | 8,000 | new term, see below |
| `ops_staff_yr` | — (didn't exist) | 60,000 | new term, see below |
| ignition axis | 50 / 150 / 400 | 154 / 307 / 614 | derived Attica ignition density, ±1 doubling |

`base_cost` dropped because the old figure conflated dock and drone into one
number that didn't match either. Splitting `drone_cost` (per-airframe) from
`base_cost` (dock only) makes the swarm-density trade-off in the sweep
legible: adding drones to an existing dock is cheaper than adding bases, and
now the numbers say so.

The two new opex terms fix a real gap: the old model had no recurring cost
beyond hardware maintenance, but every EU dock-based BVLOS operator we found
reports a bundled 30,000-50,000 EUR/base/yr that includes connectivity,
insurance, site lease, and remote-pilot oversight. We split that bundle
because remote-pilot oversight doesn't scale linearly with base count in a
swarm — one ops desk can supervise many docks. Charging the full 30-50k per
base would penalize density, which is the exact property Tier 0 argues is
valuable. So: `opex_per_base_yr = 8,000` (connectivity, insurance, site
lease, scheduled service — scales with base count) and `ops_staff_yr =
60,000` (remote-pilot + ops desk for the whole fleet — flat, fleet-wide).
This split is our judgment call, not a sourced breakdown — flag it as such
whenever the CONFIG is cited externally.

**Known limitation: `ops_staff_yr` assumes unbounded remote-supervision
capacity.** It's a flat EUR 60,000/yr fleet-wide desk with no cap on how
many bases or drones one desk can supervise — the same flat figure is
applied whether the sweep is at 4 bases or at 144 bases (288 drones), and
no sourced pilot-to-drone or pilot-to-base ratio exists anywhere in the
research, so any capacity breakpoint is an estimate, not a researched
figure. Reconciling this split back against the sourced
EUR 30,000-50,000/base/yr bundle only works at the high end: at one base
the full annualized per-base cost (hardware amortization + maintenance +
`opex_per_base_yr` + that base's share of `ops_staff_yr`) works out to
about EUR 96,000/base/yr — nearly double the top of the sourced range —
converging to about EUR 36,500/base at 144 bases, which lands inside the
range. So the decomposition reconciles with the source for larger fleets,
not small ones.

What this actually costs the pitched number, if the cap is bounded rather
than left unbounded: `ops_staff_yr` is flat, so its per-km²/yr
contribution is identical on every row (60,000 / 3,808 km² ≈ EUR 15.76),
and stepping it to "one desk per K bases" adds
`(ceil(n_bases/K) - 1) × 15.76` to a row's cost with no rerun needed. At
one desk per 25 bases: the 4-base and 9-base configs are unchanged (they
need only one desk each); 49 bases rises 479.70 -> 495.46 (+3.3%); 144
bases rises 1,379.30 -> 1,458.08 (+5.7%). At one desk per 50 bases:
everything up to 49 bases is unchanged; 144 bases rises 1,379.30 ->
1,410.81 (+2.3%). **The pitched 9-base EUR 101/km²/yr config survives
either stepping untouched**, since 9 bases sits far below any plausible
desk-capacity threshold — the unbounded-supervision assumption bites only
the high-density tail of the frontier, above roughly 25 bases, not the
headline claim. Disclose the assumption itself whenever the density
argument is pitched (no sourced capacity ratio exists), but the pitched
number does not depend on how it's resolved.

`hardware_life_yr` was tightened 5.0 -> 3.0 after this doc was first
written; the table above previously said "unchanged" and that was stale.
Reasoning: DJI warrants the Dock 3 for one year standard and sells DJI Care
Enterprise Plus extensions covering up to two battery replacements per
aircraft per year; the dock is IP56 and rated to 50C so heat itself isn't
the constraint. No vendor publishes an MTBF and no multi-year field-failure
data exists from any hot-climate operator. A manufacturer that warrants one
year and monetises extensions past it is not expecting five trouble-free
years, so 3 is a supported planning assumption — labelled "assumption,
supported," not "not found," since that's the honest category for a
reasoned estimate with no primary figure behind it.

`install_cost` was similarly tightened 20,000 -> 12,000. Reasoning: no
drone-in-a-box deployment publishes an itemised install breakdown — not in
EU tender documents, not the EIB drone finance guide, not Percepto or
Flytbase case studies. Comparable remote-site telecom and small-cell
installation (power drop, mount, backhaul) runs EUR 8,000-15,000; 12,000 is
the midpoint. Label it a proxy, not a drone-specific figure.

**Reverting either of these to the original values would LOWER the
headline cost figures**, not raise them — worth stating plainly since an
undocumented deviation that happened to make our own numbers look better
would be a red flag, and this isn't that. At `hardware_life_yr=5.0` and
`install_cost=20,000`, the 4-base/1-drone-per-base config drops from
~54 to ~50.7 EUR/km²/yr and the 9-base/1-drone-per-base config drops from
~101 to ~94.3 EUR/km²/yr. The tightened assumptions made the pitch numbers
worse, not better.

The ignition axis moved from round-number guesses (50/150/400) to values
bracketing a derived Attica estimate (154/307/614 = half/anchor/2x). See
Area 4 for the derivation.

## Area 1: unit economics

Hardware, list prices, high confidence:

| Item | EUR | Year | Source |
| --- | --- | --- | --- |
| DJI Dock 3 (dock only) | ~14,600 (from $15,890) | 2026 | [techeblog](https://www.techeblog.com/dji-dock-3-drone-in-a-box-features-specs-price/) |
| DJI Matrice 4TD (thermal drone) | ~21,500 (from $23,409) | 2026 | same |
| Base capex total, DJI stack | ~36,000 | 2026 | derived, medium confidence |
| Percepto turnkey base | 37,000-230,000 (from $40k-$250k) | 2024-25 | [percepto.co](https://percepto.co/drone-in-a-box/) |

Percepto's range is quote-based and wide (low-medium confidence) — it's a
sanity check that our DJI-stack build is on the cheap end of the market, not
a number to plug into CONFIG.

Opex, medium confidence:

- EU dock-based BVLOS opex per base per year (dock maintenance, connectivity,
  remote-pilot oversight, data): 30,000-50,000 EUR.
  [thefuture3d.com](https://www.thefuture3d.com/dock-based-drone-operations/)
- Annual hardware maintenance, medium-high use: 20-30% of hardware capex per
  year. Generic drone-industry figure, not Mediterranean-specific (low
  confidence). [flyeye.io](https://www.flyeye.io/drone-calculators-maintenance-cost/)
- Battery pack replacement: 90-740 EUR each, every 200-500 cycles (~1.5-3
  yr). Medium confidence.
  [aerovisiondrones.com](https://www.aerovisiondrones.com/what-are-the-ongoing-costs-of-owning-a-drone/)

Comparables, for pricing our EUR/km²/yr output against the market:

- OroraTech's initial Greece satellite/ground contract: 20,000,000 EUR
  (2024), high confidence.
  [ororatech.com](https://ororatech.com/resources/news-blog/greece-first-country-to-build-a-national-wildfire-system-using-ororatech-technology)
- The 200,000,000 EUR figure sometimes attached to "Greece's national
  wildfire network" is NOT OroraTech's contract — it bundles a much broader
  EU-funded programme. Correcting that misattribution here: don't cite the
  200M figure as one vendor's price.
  [euronews](https://www.euronews.com/2026/06/30/greece-is-leading-the-world-in-wildfire-prevention-thanks-to-satellites-and-ai)
- Pano AI camera station, all-in (hardware + software + 24/7 intel centre):
  ~46,000 EUR/camera/yr (from $50k). High confidence — this is the single
  strongest comparable we have, a disclosed recurring all-in price for
  wildfire monitoring, structurally similar to our per-base opex model.
  [geekwire](https://www.geekwire.com/2024/ai-trained-cameras-beat-the-naked-eye-at-spotting-first-sign-of-wildfires/)
- WA DNR's 21-camera Pano deployment: ~870,000 EUR/yr total, high
  confidence, same source.
- France lookout network: 11 centres over 6,000 km², 1,200,000 EUR total
  (~200 EUR/km² one-time). Low confidence — unclear if this is capex or
  annual, and it's a secondary source. Review of the existing fire
  detection systems in Europe and North Africa, publication 281439904 on
  researchgate.net.
- Portugal aerial patrol: ~5,000 EUR/aircraft. Low confidence, undated, same
  source.
- Castilla y León aerial patrol, IR aircraft: ~62,000 EUR/aircraft. Low
  confidence, undated, same source.
- Andalusia aerial firefighting (suppression, not monitoring — budget scale
  only): 319,200,000 EUR over 6 yr = 53,200,000 EUR/yr. High confidence.
  Included only to show suppression cost is roughly two orders of magnitude
  above anything in our monitoring model.
  [spaintenders](https://www.spaintenders.com/blogs/andalusia-awards-major-aerial-firefighting-332/)

Not found: insurance per base per year (no published figure anywhere); site
lease and permitting cost per base. These two stay unguessed — no proxy was
found close enough to defend.

Dock/drone useful life under Mediterranean heat and salt air, and the
drone-specific install cost, are no longer in this "not found" category:
no primary figure exists for either (still true, no vendor MTBF, no
itemised install breakdown anywhere), but both now carry a reasoned
estimate in CONFIG — `hardware_life_yr=3.0` (assumption, supported, see
"What changed in CONFIG and why" above) and `install_cost=12,000` (proxy
from comparable telecom/small-cell installs, same section). The honest
label for these is "assumption, supported" or "proxy," not "not found" —
that phrase is reserved for the two items above where no defensible
estimate exists at all.

## Area 2: startup graveyard

Companies surveyed: American Robotics (drone-in-a-box, first FAA BVLOS
no-visual-observer approval, acquired by Ondas 2021 for ~$70.6M
cash+equity), Airobotics (drone-in-a-box, IPO Tel Aviv 2021, ~$130M raised
lifetime, sold to Ondas 2022 for ~$18.4M — a distress sale), Ondas (NASDAQ:
ONDS, the consolidator of both), Airware (drone OS/analytics, shut down 2018
after burning $118M — the canonical hardware-capital-intensity death),
Nightingale Security (alive but thin public trail, likely stalled), Percepto
(alive, $128M raised lifetime, Series C $67M 2023, ~179 employees 2026,
survives on industrial inspection, not wildfire), Kairos Aerospace /
rebranded Insight M (aerial methane detection, $52M Series D 2024, survived
by staying in a paying vertical), Rain Industries (prepositioned autonomous
helicopters, suppression not monitoring, only $9.7M seed 2023, Sikorsky
MATRIX partnership), Pano AI (camera towers + AI + human verification, $44M
Series B 2025, $89M total raised, $100M+ contracted revenue, 250+ agency
customers), Dryad Networks Germany (gas-sensor mesh for smouldering fires,
XPRIZE Wildfire finalist 2026, $20.6M raised), OroraTech Germany (satellite
thermal, EUR 60M+ total, EUR 37M Series B extension 2025, 10 satellites),
Overstory ($43M Series B Nov 2025, utility vegetation risk), Torch Sensors
($299 solar ground sensor, raising up to $10M 2025), Chooch (computer vision
layered on existing camera networks, software-only, no hardware capex),
Probotek (Greece, 5G/AI/drone fire detection, Huawei TECH4ALL pilot partner,
pilot-stage since 2022, no major funding found — the only Greek
wildfire-drone-adjacent player we found), OFIDIA2 (EU Interreg project
Puglia/Epirus, sensors + cameras + drones, public money not VC).

Sources: dronedj.com, agfundernews.com, ir.ondas.com, techcrunch.com,
percepto.co, axios.com, dcvc.com, firerescue1.com, latitudemedia.com,
tech.eu, spacenews.com, prnewswire.com, chooch.com, huawei.com,
preventionweb.net, researchandmarkets.com.

**Critical finding, stated plainly:** no dedicated wildfire-monitoring-drone
company was found that flatly shut down with a published cause. The
graveyard is instead (a) drone-in-a-box generalists acquired at steep
markdowns after overraising, and (b) capital-burn deaths in adjacent
drone-platform plays that were never wildfire-specific. Every wildfire
player alive today sells data or alerts asset-light — cameras, satellites,
ground sensors, software — rather than owning and operating drone fleets.
The drone-fleet-owner model is itself the failure mode, not any single named
company. This directly challenges our architecture. Not softening it: if we
build the fleet-owner model, we are the only ones doing so among the
players we could find, and the ones who tried something adjacent (drone
generalists) got acquired at a discount, not funded to scale.

Recurring failure modes across the graveyard: overcapitalisation before
product-market fit; BVLOS regulatory drag stalling revenue while burn
continues; slow government budget cycles combined with seasonal,
fire-season-only revenue; the capital intensity of fleet ownership versus
asset-light sensing; suppression carrying far higher liability,
certification, and capex bars than monitoring (relevant since we are
explicitly monitoring-only for v1).

## Area 3: Greek procurement and BVLOS regulation

**Procurement timeline.** Realistic estimate for a startup with no existing
framework relationship: 12-24 months from first contact to signed contract.
Legal minimum notice is 35 days; real open-procedure timelines run 3-6
months notice-to-award for straightforward buys
([lexology](https://www.lexology.com/library/detail.aspx?g=b4f2292e-571a-4deb-9fb4-232e675b30b5),
[globallawexperts](https://globallawexperts.com/how-to-bid-for-public-tenders-in-greece/)).
Add spec drafting, budget approval, evaluation, and the routine pre-award
appeals to the Authority for Examination of Preliminary Appeals — that's
where 3-6 months becomes 12-24.

**AEGIS/ASPIDA programme.** EUR 1.7-2.1bn, funded via RRF + NSRF + an EIB
EUR 220m loan. Actions 16909-16912; Action 16911 covers drones/UAS for
aerial surveillance and is still in tender or final stages. No evidence of a
lane a two-person startup can enter directly.
([internationalfireandsafetyjournal](https://internationalfireandsafetyjournal.com/greece-to-enhance-civil-protection-equipment-through-a-e2-1-billion-aegis-program/),
[aspida.civilprotection.gov.gr](https://aspida.civilprotection.gov.gr/en/initiatives-projects-rrf/))

**Existing state drone fleet.** Reported at 40 to 80 to 100 drones across
2024-2026 press coverage; supplier and per-unit value undisclosed.
([iefimerida](https://www.iefimerida.gr/ellada/100-drones-pyrosbestiki-kai-politiki-prostasia))

**Fastest paths to a paid pilot, ranked:**

1. INFOSOC innovation procurement (pre-commercial procurement, PCP) with the
   Ministry of Climate Crisis and Civil Protection plus the Fire Brigade, on
   fire and flood prediction from sensor data — closest SME fit found,
   bypasses full open tender.
   ([ketmarket](https://ketmarket.eu/funding/demand-led-innovation-for-civil-security-through-pre-commercial-procurement-pcp/))
2. EIC Innovation Procurement / InnoMatch — pairs EIC-backed startups with a
   public buyer, but requires prior EIC backing as a precondition.
   ([eic.ec.europa.eu](https://eic.ec.europa.eu/eic-funding-opportunities/bas/eic-innovation-procurement-programme_en))
3. rescEU — dead end for direct startup sales, member-state reserve assets
   only. Listed for context, not as a path.
4. Full open AEGIS tender — slowest.

**Regulatory correction, important.** The project index currently states as
fact that HCAA granted a SORA authorization in Greece in Jan 2026. That
premise is unverified. The only public Greek SORA approval we found is Duke
Robotics Hellas, Jan 2026, and it was for an Insulator Cleaning drone
(power-line inspection), not wildfire or forest work — and the source does
not confirm BVLOS was actually granted.
([manilatimes](https://www.manilatimes.net/2026/01/13/tmt-newswire/globenewswire/duke-robotics-secures-regulatory-approval-for-ic-drone-operations-in-greece/2258027/amp))
Correct the index; don't build a regulatory timeline assumption on this.

**Stronger, confirmed precedent.** AESA granted Telefónica Spain the first
fully remote drone-in-a-box BVLOS authorization, announced April 2026,
explicitly covering wildfire surveillance and environmental monitoring, with
the remote pilot hundreds of km away. Safety case developed with Murzilli
Consulting.
([unmannedairspace](https://www.unmannedairspace.info/uncategorized/spain-approves-first-fully-remote-drone-in-a-box-bvlos-operation/),
[dronewatch](https://www.dronewatch.eu/spain-approves-first-fully-remote-drone-in-a-box-bvlos-operation/))
Recommend requesting that safety case as a template — it's the closest
real-world analog to what we'd need to file.

**BVLOS steps, roughly:** register as a UAS operator with HCAA (weeks);
prepare the SORA case — ConOps plus ground and air risk assessment plus
mitigations — typically 2-6 months of work; HCAA review, duration not
published anywhere. Budget 12-18+ months overall; do not build the funding
plan on fast approval.

**Open unknowns:** actual HCAA SORA processing time and cost; whether AEGIS
Action 16911's drone lines are open tender or already awarded; INFOSOC pilot
scope, timeline, and whether SME applications are currently open; no EASA
U-space or 2026 package confirmation found. We did not pull diavgeia.gov.gr
or ESIDIS records directly — a targeted diavgeia search for "Πυροσβεστικό
Σώμα" + "μη επανδρωμένα" would likely surface the actual supplier and price
of the 40-80-100 drone fleet. This is the single highest-value unfinished
lookup from this pass.

## Area 4: ignition density and fire model

**Ignition density derivation, shown in full.** Hellenic Fire Service
reported 8,511 forest fire incidents nationally, 1 Jan-31 Aug 2023, stated
as -20% versus the same-period long-term average (Fire Service daily
bulletins via climatebook.gr, naftemporiki.gr). Back out the average:
8,511 / 0.80 ≈ 10,640 fires per season nationally — and that window already
covers essentially the whole season, since the core fire season is Jun-Sep.
Greece land area: 131,957 km². So 10,640 / 131,957 × 1,000 ≈ 80.6 ignitions
per 1,000 km² per season. Over our 3,808 km² Attica-sized domain that's
≈307 per season — the anchor value now in CONFIG's ignition axis.

No Attica-specific ignition count was found — only burn extent (38-42% of
Attica forest burned 2017-2026, per meteo.gr/NOA analysis of Copernicus
Rapid Mapping). Attica runs hotter than the national average because of
wildland-urban interface and human ignition, so 80.6/1000km² is a floor, not
a match. No citable Attica multiplier exists — the 2x we used to set the
axis's upper bound is an explicit assumption, not a sourced figure. That's
why the axis is 154/307/614: half-anchor, anchor, double-anchor, bracketing
uncertainty around a real derivation rather than presenting a false-precision
Attica number.

**Fire size distribution: not verified.** EFFIS's public burnt-area layer
only maps scars ≥30 ha via MODIS/Sentinel-2, which structurally excludes
small fires from its headline statistics. The widely-cited Mediterranean
pattern — a low single-digit percentage of ignitions produce most burned
area, most ignitions self-extinguish or stay under 1 ha — is consistent with
what we found but no Greece-specific citable number was obtained. Do not
hard-code this into the model.

**Spread model: no single unified Greek operational model exists.** The Fire
Service leans on ground observation plus EFFIS/Copernicus fire danger and
rapid-mapping layers, not a published in-house physics model. NOA (National
Observatory of Athens — FLAME pyro-meteorology team, BSM_NOA burn-scar
mapping) is the main research group, but it's focused on post-fire mapping
and smoke transport, not pre-fire spread prediction. No Greek-specific fuel
model set exists.

Recommendation for Tier 1: Cell2Fire (Frontiers 2021,
[github.com/humnetlab/Cell2Fire](https://github.com/humnetlab/Cell2Fire))
with Scott & Burgan 40 fuels, hand-mapped to Greek CORINE / Mesogeos
land-cover classes. Cell2Fire natively supports FBP, Scott & Burgan 40, and
KITRAL, but has no Mediterranean fuel set out of the box; S&B40 has closer
analogues to Mediterranean maquis than Anderson 13. The CORINE-to-S&B40
crosswalk is engineering work we do ourselves — standard practice in EU
wildfire literature, not a research gap.

Mesogeos (Kondylatos et al., NeurIPS 2023,
[orionlab.space.noa.gr/mesogeos](https://orionlab.space.noa.gr/mesogeos),
[github.com/Orion-AI-Lab/mesogeos](https://github.com/Orion-AI-Lab/mesogeos))
is the right data layer: a 1km daily datacube 2006-2022, Mediterranean-wide,
built by NOA, with ignition records, burned-area ground truth, and 27 driver
variables. Use it to calibrate ignition density and fuel moisture, not as a
spread engine itself.

**Detection baseline to beat.** Current ignition-to-brigade-alert in Greece
is reported at roughly 20-30 minutes; both Huawei and Greek officials cite
response within 15 minutes as the threshold that materially changes
containment odds (PBS News Hour and CTIF coverage of the satellite rollout,
Huawei TECH4ALL). Both are press-sourced, not a published Fire Service
statistic — fine to cite in a pitch, weak for a technical appendix. State
that caveat wherever this number is used.

## What we still could not find

- Insurance per base per year (no published figure at all).
- Site lease and permitting cost per base.
- Attica-specific ignition count (only burn-extent data exists).
- Greece-specific fire-size distribution (EFFIS's 30ha floor excludes the
  small fires that matter most for a monitoring pitch).
- HCAA SORA processing time and cost.
- Whether AEGIS Action 16911's drone lines are open tender or already
  awarded.
- INFOSOC pilot scope, timeline, and current SME eligibility.
- Supplier and per-unit price of Greece's existing 40-80-100 state drone
  fleet (diavgeia.gov.gr search not yet run — highest-value next lookup).

## What this changes strategically

The unit-economics numbers land close to where the old placeholders had
them, which means the Tier 0 sweep's qualitative shape (density beats raw
fleet size, cost curve knee near EUR 100-200/km²/yr) likely survives —
that needs re-running with the new CONFIG to confirm, not assumed.

The graveyard finding is the sharper strategic signal: nobody who owns and
operates a drone fleet for wildfire work has survived to scale on that model
alone. Every survivor sells asset-light data or alerts. Two live options:
(1) treat the fleet as the differentiator and accept we're testing an
unproven model, going in with eyes open about why others avoided it, or (2)
treat the fleet as a means to sell a data/alert product structurally closer
to Pano AI's, which has the strongest disclosed comparable pricing we found
(~46k EUR/camera/yr all-in). The Pano comparable is also useful directly:
our EUR/km²/yr output should be checked against what a Pano-equivalent
coverage density would cost, not just against satellite programmes at a
different order of magnitude.

The procurement and BVLOS findings both push out the revenue timeline
materially: 12-24 months to a signed contract, 12-18+ months for BVLOS
authorization, likely run in parallel but neither compressible by
being small. The Spain BVLOS precedent is worth pursuing directly (request
the safety case) since it's the only confirmed match for our actual
operating model (remote pilot, drone-in-a-box, wildfire scope). The Greek
SORA claim in the project index was wrong and should stop circulating.

The ignition-density number (307/season over the Attica-sized domain) is
now a derived floor with a stated 2x uncertainty band, not a guess — that's
the single most load-bearing correction from this pass, since it's the
input the whole cost-per-km² result depends on.

## Withdrawn: the ~EUR 54/km2/yr frontier point

The 4-base / 1-drone / 26 km config that appears at the cheap end of the
Pareto frontier is **a gate artifact and must not be cited.**

It sits exactly on the `max_unserved_share = 0.10` quality gate. At the
307-ignition anchor with a 30 s launch latency, its unserved share across the
five false-alarm rates reads:

| fp_rate | unserved_share | gate |
|---|---|---|
| 0.05 | 0.1039 | fail |
| 0.15 | 0.1023 | fail |
| 0.25 | 0.0985 | **pass, by 0.0015** |
| 0.35 | 0.1076 | fail |
| 0.50 | 0.1110 | fail |

It clears the gate in one case out of five. It reached the frontier by winning
a coin flip against the feasibility test at `seasons_per_config = 50`, not by
being feasible. A config whose feasibility flips with the false-alarm rate —
which cannot improve response time, only consume drones — is a sampling
artifact.

This also sharpens the earlier caveat about `fp_rate` values appearing on the
frontier. The noise is not perturbing p90; it is crossing the feasibility
threshold. Confirming that reading: a different `fp_rate` "wins" in different
density panels (0.25 gives the lowest p90 in the 307 panel, 0.35 in the 154
panel), which is what pure sampling noise looks like and what a real
false-alarm effect would not.

The comparison at lines above — that reverting `hardware_life_yr` and
`install_cost` to this doc's original values would move ~54 to ~50.7 — remains
valid as a cost-sensitivity check, but the ~54 figure it references is a
withdrawn row.

**EUR 101/km2/yr (9 bases, 1 drone each) is the sole defensible headline.**
Across the same five false-alarm rates its unserved share is 0.00104, 0.00119,
0.00159, 0.00151, 0.00201 and its p90 is 10.05 to 10.15 minutes — insensitive
on both axes, and nowhere near the gate.
