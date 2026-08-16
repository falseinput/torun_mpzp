# torun_mpzp

Build a single Cloud Optimized GeoTIFF (COG) of every binding local zoning plan
in Toruń, and publish it to Cloudflare R2.

A local zoning plan is a *miejscowy plan zagospodarowania przestrzennego*, or
MPZP. Each plan is a georeferenced scan of a paper drawing. The plans cover
6,805 ha, about 59% of the city.

## Data source

The city registers its planning datasets in the GUGiK [EZiUDP][eziudp] registry
under `PL.ZIPPZP.3853` (Prezydent Miasta Torunia, TERYT `046301_1`). Voxly hosts
the GeoServer that serves them:

- WFS: `https://voxly.pl/geoserver/voxly_app_0463011/wfs`
- WMS: `https://voxly.pl/geoserver/voxly_app_0463011/wms`

The `app.AktPlanowaniaPrzestrzennego.MPZP` layer holds 245 plans. Each feature
carries plan metadata and `rysunek_lacze`, a link to the drawing. Four plans span
two sheets and pack both links into that one field as a comma-separated string,
so the layer resolves to 249 rasters totalling about 2.17 GB.

The drawings are raster scans. The dataset contains no vector zoning polygons,
so you cannot query land use from it directly.

## Pipeline

| Script | Input | Output |
|--------|-------|--------|
| `scripts/fetch_manifest.py`   | WFS            | `manifest.json` |
| `scripts/download_sources.py` | `manifest.json`| `data/input/*.tiff` |
| `scripts/create_cog`          | `data/input/`  | `data/output/output_cog.tiff` |

To run the pipeline locally:

```sh
python3 scripts/fetch_manifest.py -o manifest.json
python3 scripts/download_sources.py -m manifest.json -o data/input
./scripts/create_cog data/input data/output 18
```

`manifest.json` is committed to the repository. Run `git diff manifest.json` to
see what the city changed since the last build.

## Resolution

The build snaps the mosaic to a Web Mercator zoom grid, so the tile server never
resamples. Source sheets range from 0.0999 to 1.6952 m/px.

| Zoom | Ground m/px | Mosaic | COG size | Fits a GitHub runner? |
|------|-------------|--------|----------|-----------------------|
| 18   | 0.3593      | 52,113 × 31,073   | ~0.7 GB  | Yes |
| 19   | 0.1797      | 104,226 × 62,146  | ~2.6 GB  | Marginal |
| 20   | 0.0898      | 208,452 × 124,292 | ~10.5 GB | No |

z18 is the default because GitHub caps hosted jobs at 6 hours. A z19 build hit
that cap after 294 minutes of warping on a 2-core runner. z18 needs a quarter of
the pixels.

Two runner limits constrain this pipeline:

- **Time.** The job cap is 6 hours and cannot be raised. Public repositories get
  4-core runners; private ones get 2-core.
- **Disk.** The runner image leaves about 14 GB free. The build needs room for
  the sources, an intermediate, and the output at once, so the workflow deletes
  unused toolchains first.

To raise the resolution once you know a full build fits, pass the `zoom` input.
Note that z19 matches the source data more closely: most sheets fall between
0.17 and 0.25 m/px, so z18 discards real detail on the sharper ones.

## Mosaic settings

These GDAL flags are not the defaults, and each one prevents a specific failure:

| Flag | Reason |
|------|--------|
| `gdalbuildvrt -resolution highest` | The `average` default rebuilds every sheet at the mean resolution, destroying detail before the warp starts. |
| `-r lanczos` | Nearest-neighbour drops hairline strokes and shreds annotation text when a sheet is downsampled. |
| `COMPRESS=DEFLATE PREDICTOR=2` | Lossless, and compresses these mostly-white scans about 27:1. |
| `OVERVIEW_RESAMPLING=AVERAGE` | The COG default thins line work until it breaks up at low zoom. |

GDAL treats the source alpha bands as masks, so overlapping sheets composite
correctly instead of punching transparent holes in each other.

Web Mercator metres are not ground metres. At Toruń's latitude the scale factor
is 1.662, so a `-tr` value of 0.5 means 0.30 m on the ground.

## Publishing

`.github/workflows/build.yml` runs monthly and on manual dispatch. It skips the
build when `manifest.json` is unchanged, so an unchanged month costs about a
minute. It publishes `mpzp.tif` and `manifest.json`.

Set these repository secrets:

| Secret | Value |
|--------|-------|
| `R2_ACCOUNT_ID`        | Cloudflare account ID, used as the R2 endpoint subdomain |
| `R2_ACCESS_KEY_ID`     | R2 API token access key |
| `R2_SECRET_ACCESS_KEY` | R2 API token secret |
| `R2_BUCKET`            | Destination bucket name, not a URL |

Grant the API token **Object Read & Write**. R2 tokens are read-only by default,
which lets the build list the bucket and then fail on upload.

### Bucket CORS

A browser reads a COG through ranged cross-origin GETs, so the bucket needs a
CORS policy. Apply `r2-cors.json` in the Cloudflare dashboard under
**R2 → bucket → Settings → CORS Policy**, or from the command line:

```sh
wrangler r2 bucket cors set "$R2_BUCKET" --file r2-cors.json
```

The S3 API nests the same rules under `CORSRules`:

```sh
aws s3api put-bucket-cors --bucket "$R2_BUCKET" \
  --endpoint-url "https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com" \
  --cors-configuration "$(jq '{CORSRules: .}' r2-cors.json)"
```

The policy needs three things to work:

- `range` in `AllowedHeaders`. `Range` is not a CORS-safelisted request header,
  so every ranged GET preflights. Without this, reads fail immediately.
- `Content-Range` and `Accept-Ranges` in `ExposeHeaders`. Neither is a safelisted
  response header, so without this the browser hides the headers the reader needs.
- Exact origins. An origin must match on scheme, host, and port. `localhost` and
  `127.0.0.1` are different origins.

Edit the origin list to match where you serve from, then make the bucket readable
through its `r2.dev` URL or a custom domain.

## License

MIT. See [LICENSE](LICENSE).

The zoning plans themselves are public information published by the City of
Toruń, and are not covered by this repository's license.

[eziudp]: https://integracja.gugik.gov.pl/eziudp/
