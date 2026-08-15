#!/usr/bin/env python3
"""Download the MPZP plan drawings listed in the manifest.

Incremental: a sheet already on disk whose size matches the server's is left
alone, so a cache-restored input directory only pulls what actually changed.

Note voxly.pl answers HEAD with 401 but serves GET (including Range) fine, so
the size probe is a one-byte ranged GET rather than a HEAD.
"""

import argparse
import concurrent.futures as futures
import json
import os
import sys
import time
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def remote_size(url: str, timeout: int) -> int | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_range = resp.headers.get("Content-Range", "")
    return int(content_range.rsplit("/", 1)[-1]) if "/" in content_range else None


def download(url: str, dest: str, timeout: int) -> int:
    tmp = f"{dest}.part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    os.replace(tmp, dest)
    return os.path.getsize(dest)


def fetch_one(task: tuple[str, str], out_dir: str, timeout: int, retries: int) -> tuple[str, str, int]:
    filename, url = task
    dest = os.path.join(out_dir, filename)

    for attempt in range(retries):
        try:
            expected = remote_size(url, timeout)
            if expected and os.path.exists(dest) and os.path.getsize(dest) == expected:
                return filename, "cached", expected

            size = download(url, dest, timeout)
            if expected and size != expected:
                raise OSError(f"size mismatch: got {size}, expected {expected}")
            return filename, "downloaded", size
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            if attempt == retries - 1:
                return filename, f"FAILED: {type(exc).__name__}: {exc}", 0
            time.sleep(2 ** attempt)
    return filename, "FAILED", 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--manifest", default="manifest.json")
    ap.add_argument("-o", "--output-dir", default="data/input")
    # Deliberately modest. This is a municipal file host, not a CDN.
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)

    os.makedirs(args.output_dir, exist_ok=True)
    tasks = [
        (raster["filename"], raster["url"])
        for plan in manifest["plans"]
        for raster in plan["rasters"]
    ]
    print(f"{len(tasks)} rasters, {args.jobs} concurrent -> {args.output_dir}")

    counts = {"cached": 0, "downloaded": 0}
    total_bytes = 0
    failures = []

    with futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        pending = [pool.submit(fetch_one, t, args.output_dir, args.timeout, args.retries) for t in tasks]
        for done, future in enumerate(futures.as_completed(pending), 1):
            filename, status, size = future.result()
            total_bytes += size
            if status.startswith("FAILED"):
                failures.append((filename, status))
                print(f"[{done}/{len(tasks)}] {filename}: {status}", file=sys.stderr)
            else:
                counts[status] += 1
                if status == "downloaded":
                    print(f"[{done}/{len(tasks)}] {filename} ({size / 1e6:.1f} MB)")

    print(
        f"\ndownloaded {counts['downloaded']}, reused {counts['cached']}, "
        f"failed {len(failures)}  |  {total_bytes / 1e9:.2f} GB on disk"
    )
    if failures:
        print("\nfailures:", file=sys.stderr)
        for filename, status in failures:
            print(f"  {filename}: {status}", file=sys.stderr)
        return 1

    # A partial mosaic would silently ship holes, so treat any gap as fatal.
    expected = {f for f, _ in tasks}
    missing = sorted(f for f in expected if not os.path.exists(os.path.join(args.output_dir, f)))
    if missing:
        print(f"\nmissing {len(missing)} files: {missing[:5]}", file=sys.stderr)
        return 1

    # With a restored cache the directory can still hold sheets the city has since
    # withdrawn or reissued under a new filename; they would otherwise be mosaicked
    # in on top of their own replacements.
    for stale in sorted(set(os.listdir(args.output_dir)) - expected):
        path = os.path.join(args.output_dir, stale)
        if os.path.isfile(path):
            print(f"pruning stale sheet: {stale}")
            os.remove(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
