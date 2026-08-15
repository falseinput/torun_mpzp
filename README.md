# torun_mpzp

Builds a single Cloud Optimized GeoTIFF of every binding local zoning plan
(miejscowy plan zagospodarowania przestrzennego) in Toruń, and publishes it to
Cloudflare R2.

## Where the data comes from

The city registers its planning datasets in GUGiK's [EZiUDP][eziudp] under
`PL.ZIPPZP.3853` (Prezydent Miasta Torunia, TERYT `046301_1`). The dataset is
served from a GeoServer run by Voxly:

- WFS — `https://voxly.pl/geoserver/voxly_app_0463011/wfs`
- WMS — `https://voxly.pl/geoserver/voxly_app_0463011/wms`

`app.AktPlanowaniaPrzestrzennego.MPZP` holds **245 plans**. Each feature carries
plan metadata plus `rysunek_lacze`, a link to the georeferenced drawing. Four
plans are drawn on two sheets each, packed into that field as a comma-separated
string, so there are **249 rasters totalling ~2.17 GB**.

### What this data is not

The APP 2.0 schema stores only the plan *boundary*, a reference to the drawing,
and the adopting resolution. There are **no vector zoning polygons** — the
land-use designations exist solely as pixels in the scanned drawings. That is a
limitation of the national standard, not of Toruń; the 2020 regulation never
required vector designations for MPZP.

If you want vector zoning geometry, use the **plan ogólny** instead
(`PL.ZIPPZP.9733`, layer `app.StrefaPlanistyczna`): 1702 polygons with `symbol`,
`nazwa`, height/intensity/biologically-active-area limits and permitted land-use
profiles, in force since 2026-06-18. It is the coarser strategic layer, but it is
real vector data.

## Pipeline

```
scripts/fetch_manifest.py     WFS  -> manifest.json (plan ids, versions, raster urls)
scripts/download_sources.py   manifest.json -> data/input/*.tiff   (incremental)
scripts/create_cog            data/input/ -> data/output/output_cog.tiff
```

Run it locally:

```sh
python3 scripts/fetch_manifest.py -o manifest.json
python3 scripts/download_sources.py -m manifest.json -o data/input
./scripts/create_cog data/input data/output 19
```

`manifest.json` is committed. `git diff manifest.json` after a run is the
changelog of what the city published.

### Resolution

The mosaic is snapped to a Web Mercator zoom grid so the tile server never has to
resample. Source sheets range from **0.0999 to 1.6952 m/px** — a 17× spread.

| zoom | 3857 m/px | ground m/px at Toruń | mosaic | COG size | warp |
|------|-----------|----------------------|--------|----------|------|
| 18   | 0.5972    | 0.3593               | 52,113 × 31,073   | ~0.7 GB  | ~20 min |
| 19   | 0.2986    | 0.1797               | 104,226 × 62,146  | ~2.6 GB  | ~80 min |
| 20   | 0.1493    | 0.0898               | 208,452 × 124,292 | ~10.5 GB | ~5 h |

**z19 is the default.** Area-weighted, only ~4% of plan coverage was scanned finer
than 0.10 m/px, and most sheets sit at 0.17–0.25 m/px, so z19 is at or near native
for the bulk of the data. z20 is not practical here: ~10.5 GB will not fit on a
GitHub runner alongside its inputs and intermediate, and it is an unreasonable
object to hand a browser.

Figures are extrapolated from a measured 22-plan z19 build (45,427 × 26,225,
227 MB, 14m29s) at **1.250 bytes per covered pixel**, scaled over the 6,805 ha the
plans actually cover — which independently matches the city's published MPZP
coverage figure of 6,814 ha.

Note that Web Mercator metres are not ground metres — at Toruń's latitude the scale
factor is 1.662, so a `-tr` value of 0.5 means 0.30 m on the ground, not 0.5 m.

### Why the mosaic is built the way it is

- `gdalbuildvrt -resolution highest` — the default is `average`, which with a 17×
  resolution spread rebuilds every sheet at the mean (~0.57 m/px) and throws away
  the detail of the sharp ones before the warp starts.
- `-r lanczos`, not `near` — these are scanned line drawings; nearest-neighbour
  drops hairline strokes and shreds annotation text wherever a sheet is downsampled.
- `COMPRESS=DEFLATE PREDICTOR=2` — lossless, and these mostly-white scans compress
  roughly 27:1. Uncompressed would be hundreds of GB.
- `OVERVIEW_RESAMPLING=AVERAGE` — the COG default thins line work until it visibly
  breaks up when zoomed out.
- Source alpha bands are honoured as masks, so the 31 overlapping sheet pairs
  composite correctly instead of punching transparent holes in each other.

## Publishing

`.github/workflows/build.yml` runs monthly and on manual dispatch. It skips the
whole build when `manifest.json` is unchanged, so an unchanged month costs about a
minute.

Required repository secrets:

| secret | meaning |
|--------|---------|
| `R2_ACCOUNT_ID`        | Cloudflare account id (the R2 endpoint subdomain) |
| `R2_ACCESS_KEY_ID`     | R2 API token access key |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret |
| `R2_BUCKET`            | destination bucket name |

Published objects: `mpzp.tif` and `manifest.json`.

### Bucket configuration

Reading a COG from a browser means ranged cross-origin GETs, so the bucket needs
CORS allowing your site's origin, `GET`/`HEAD`, the `Range` request header, and
`Content-Range`/`Content-Length`/`Accept-Ranges` exposed. Serve it through a
public r2.dev URL or a custom domain.

[eziudp]: https://integracja.gugik.gov.pl/eziudp/
