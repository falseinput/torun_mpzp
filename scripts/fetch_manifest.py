#!/usr/bin/env python3
"""Query the City of Torun APP WFS and write a manifest of MPZP plan drawings.

The manifest is committed to the repo, so `git diff manifest.json` after a run
shows exactly which plans the city changed. `wersjaid` is the city's own version
stamp for a plan, which is what the incremental download keys on.

Registered in GUGiK's EZiUDP as PL.ZIPPZP.3853 (Prezydent Miasta Torunia,
TERYT 046301_1).
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

WFS = "https://voxly.pl/geoserver/voxly_app_0463011/wfs"
TYPENAME = "voxly_app_0463011:app.AktPlanowaniaPrzestrzennego.MPZP"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def fetch_features(timeout: int) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": TYPENAME,
            "outputFormat": "application/json",
            "srsName": "urn:ogc:def:crs:EPSG::2180",
        }
    )
    req = urllib.request.Request(f"{WFS}?{query}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["features"]


def build(features: list[dict]) -> dict:
    plans = []
    for feat in features:
        p = feat["properties"]
        # A handful of plans are drawn on more than one sheet, and the city packs
        # those into a single comma-separated string rather than a list.
        rasters = [u.strip() for u in (p.get("rysunek_lacze") or "").split(",") if u.strip()]
        if not rasters:
            print(f"  warning: {p.get('lokalnyid')} has no raster link", file=sys.stderr)
        plans.append(
            {
                "lokalnyId": p["lokalnyid"],
                "wersjaId": p["wersjaid"],
                "tytul": p.get("tytul"),
                "obowiazujeOd": p.get("obowiazujeod"),
                "gml": p.get("lacze_gml"),
                "rasters": [
                    {"url": u, "filename": os.path.basename(urllib.parse.urlparse(u).path)}
                    for u in rasters
                ],
            }
        )

    plans.sort(key=lambda x: x["lokalnyId"])

    # Cache key for CI: changes only when a plan is added, removed or reissued.
    digest = hashlib.sha256(
        "\n".join(f"{p['lokalnyId']}:{p['wersjaId']}" for p in plans).encode()
    ).hexdigest()

    return {
        "source": {"wfs": WFS, "typeName": TYPENAME, "datasetId": "PL.ZIPPZP.3853"},
        "planCount": len(plans),
        "rasterCount": sum(len(p["rasters"]) for p in plans),
        "versionHash": digest,
        "plans": plans,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="manifest.json")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    print(f"querying {TYPENAME} ...")
    manifest = build(fetch_features(args.timeout))

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")

    print(
        f"{manifest['planCount']} plans, {manifest['rasterCount']} rasters "
        f"-> {args.output}  (version {manifest['versionHash'][:12]})"
    )
    # Consumed by the workflow to key actions/cache.
    if gh := os.environ.get("GITHUB_OUTPUT"):
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write(f"version_hash={manifest['versionHash']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
