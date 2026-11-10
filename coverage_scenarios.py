import math


PROFILES = {
    "reference": (46.0, .25, 60.0),
    "short_endurance": (36.0, .25, 60.0),
    "larger_reserve": (46.0, .35, 60.0),
    "slow_launch": (46.0, .25, 180.0),
    "combined": (36.0, .35, 180.0),
}


def make_scenarios():
    diagonal = 12.0 / math.sqrt(2)
    winds = (
        (12.0, 0.0), (diagonal, diagonal), (0.0, 12.0), (-diagonal, diagonal),
        (-12.0, 0.0), (-diagonal, -diagonal), (0.0, -12.0), (diagonal, -diagonal),
    )
    cases = []

    def add(count, speed, heading, wind, profile, offline):
        endurance, reserve, launch = PROFILES[profile]
        heading_id = "calm" if heading is None else f"h{heading:03d}"
        outage_id = "_".join(map(str, offline)) if offline else "none"
        cases.append({
            "case_id": f"b{count}-w{speed:g}-{heading_id}-{profile}-off{outage_id}",
            "n_bases": count, "wind_mps": list(wind), "wind_speed_mps": float(speed),
            "heading_deg": heading, "profile": profile, "offline_bases": list(offline),
            "airspeed_mps": 18.0, "endurance_min": endurance,
            "reserve_fraction": reserve, "launch_latency_s": launch,
        })

    for count in (9, 25):
        for heading, wind in zip(range(0, 360, 45), winds):
            add(count, 12, heading, wind, "reference", [])
            for site in range(count):
                add(count, 12, heading, wind, "reference", [site])
            for pair in ([0, 1], [0, (count - 1) // 2]):
                add(count, 12, heading, wind, "reference", pair)
            for profile in tuple(PROFILES)[1:]:
                add(count, 12, heading, wind, profile, [])
        add(count, 0, None, (0.0, 0.0), "reference", [])
        add(count, 13, 0, (13.0, 0.0), "reference", [])
    if len(cases) != 388 or len({case["case_id"] for case in cases}) != 388:
        raise ValueError("Coverage design must contain exactly 388 unique scenarios")
    return cases
