"""Resolve each taluka in the loaded data to real coordinates, once.

    python scripts/geocode_talukas.py

Uses Nominatim, OpenStreetMap's own geocoder, and writes the result to
frontend/lib/taluka-coords.json so the map ships with a cached file rather
than geocoding on every page load.

Two rules this script follows, both from the OSM usage policy:
  * at most one request per second, serially;
  * a descriptive, non-personal User-Agent.

Any taluka that cannot be resolved is written with coordinates of null rather
than a guess. The map then omits it and says so, because a marker in the wrong
place is worse than a missing one in a government-facing tool.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.geo import known_talukas  # noqa: E402

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "HackFusion-GrievanceDemo/1.0 (hackathon prototype)"
OUT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "lib"
    / "taluka-coords.json"
)

#: The district every taluka name is qualified with. Read from the data's own
#: notes rather than hardcoded policy: it only disambiguates the search.
DISTRICT_QUERY = "Nanded, Maharashtra, India"


def geocode(client: httpx.Client, taluka: str) -> dict | None:
    response = client.get(
        NOMINATIM,
        params={
            "q": f"{taluka}, {DISTRICT_QUERY}",
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 0,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=20.0,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    hit = results[0]
    return {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "display_name": hit.get("display_name"),
        "osm_type": hit.get("osm_type"),
        "osm_id": hit.get("osm_id"),
    }


def main() -> int:
    init_db()
    with SessionLocal() as session:
        talukas = known_talukas(session)

    if not talukas:
        print("no talukas loaded; run scripts/load_data.py first")
        return 1

    print(f"geocoding {len(talukas)} taluka(s) via Nominatim, 1 per second")
    out: dict[str, dict | None] = {}

    with httpx.Client() as client:
        for index, taluka in enumerate(talukas, start=1):
            try:
                hit = geocode(client, taluka)
            except Exception as exc:  # network, rate limit, anything
                print(f"  {index:>2}. {taluka:<16} FAILED ({exc})")
                out[taluka] = None
            else:
                if hit:
                    print(f"  {index:>2}. {taluka:<16} {hit['lat']:.4f}, {hit['lon']:.4f}")
                else:
                    print(f"  {index:>2}. {taluka:<16} no match")
                out[taluka] = hit
            # Serial, one per second: the published usage policy.
            if index < len(talukas):
                time.sleep(1.1)

    resolved = sum(1 for v in out.values() if v)
    payload = {
        "source": "Nominatim / OpenStreetMap",
        "licence": "© OpenStreetMap contributors, ODbL",
        "query_suffix": DISTRICT_QUERY,
        "resolved": resolved,
        "total": len(talukas),
        "note": (
            "Centroids returned by a place search, not administrative "
            "boundaries. A taluka with null coordinates was not resolved and "
            "is omitted from the map rather than placed by guesswork."
        ),
        "talukas": out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print(f"resolved {resolved}/{len(talukas)}")
    return 0 if resolved else 1


if __name__ == "__main__":
    raise SystemExit(main())
