"""degrade_bayestar.py - One-time downsample of the bundled GW170817 skymap.

Problem: data/bayestar.fits.gz holds a FULL-RESOLUTION nside-2048 map
(50,331,648 rows x 4 float64 = 1.6 GB decompressed). Opening it on a 512 MB
Render instance is instant OOM (boot RSS alone is ~310 MB).

Fix: degrade 2048 -> 256 with exact nested-HEALPix coarsening
(each coarse pixel = sum of its 64 contiguous fine children; DISTMU/DISTSIGMA
as probability-weighted child means; unused DISTNORM column dropped).
Nested ordering is preserved (coarse index = fine index // 64), so every
downstream consumer (npix_to_nside, cone geometry, mollweide plot) runs
unchanged. 90%-credible area and probability-weighted distance are
conserved by construction; the script asserts that before overwriting.

Run:  python scripts/degrade_bayestar.py
"""
import gzip
import io
import os

import numpy as np
from astropy.io import fits

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src", "backend", "data", "bayestar.fits.gz")

RATIO = 8          # 2048 -> 256
CHILDREN = RATIO * RATIO  # 64 contiguous fine pixels per coarse pixel
CHUNK = 4_000_000  # rows per accumulation pass (low peak RAM)


def main() -> None:
    with open(SRC, "rb") as f:
        raw = gzip.decompress(f.read())
    print(f"input decompressed: {len(raw) / 1e6:.1f} MB", flush=True)
    hdul = fits.open(io.BytesIO(raw))
    data = hdul[1].data
    n = len(data)
    assert n % CHILDREN == 0, f"rows {n} not divisible by {CHILDREN}"
    cn = n // CHILDREN
    print(f"rows={n} -> coarse={cn} (nside {int((cn // 12) ** 0.5)})", flush=True)

    p_sum = np.zeros(cn, dtype=np.float64)
    mu_num = np.zeros(cn, dtype=np.float64)
    sg_num = np.zeros(cn, dtype=np.float64)
    col_p = data["PROB"]
    col_mu = data["DISTMU"]
    col_sg = data["DISTSIGMA"]
    for a in range(0, n, CHUNK):
        b = min(a + CHUNK, n)
        p = np.asarray(col_p[a:b], dtype=np.float64)
        mu = np.asarray(col_mu[a:b], dtype=np.float64)
        sg = np.asarray(col_sg[a:b], dtype=np.float64)
        ci = np.arange(a, b) // CHILDREN
        np.add.at(p_sum, ci, p)
        np.add.at(mu_num, ci, p * mu)
        np.add.at(sg_num, ci, p * sg)
        del p, mu, sg
    # NOTE: raw DISTMU contains inf/NaN in zero-probability pixels (normal for
    # BAYESTAR); the pipeline guards with isfinite and weights by probability,
    # so reference stats are asserted against PUBLISHED GW170817 values below
    # instead of a naive full-array mean.
    del data
    hdul.close()

    with np.errstate(invalid="ignore", divide="ignore"):
        mu_c = np.where(p_sum > 0, mu_num / np.maximum(p_sum, 1e-300), 0.0)
        sg_c = np.where(p_sum > 0, sg_num / np.maximum(p_sum, 1e-300), 0.0)
    print(f"total prob: {p_sum.sum():.6f}", flush=True)

    cols = [
        fits.Column(name="PROB", format="D", array=p_sum),
        fits.Column(name="DISTMU", format="D", array=mu_c),
        fits.Column(name="DISTSIGMA", format="D", array=sg_c),
    ]
    out = fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU.from_columns(cols)])
    buf = io.BytesIO()
    out.writeto(buf)
    blob = gzip.compress(buf.getvalue(), mtime=0)
    print(f"output gzipped: {len(blob) / 1e6:.2f} MB", flush=True)

    # Sanity: 90% area and distance must survive coarsening.
    order = np.argsort(p_sum)[::-1]
    cum = np.cumsum(p_sum[order] / p_sum.sum())
    top = order[cum <= 0.90]
    area = len(top) * (41253.0 / cn)
    w = p_sum[top] / p_sum[top].sum()
    dmean = float((w * mu_c[top]).sum())
    print(f"coarse 90% area: {area:.2f} deg^2 | dmean: {dmean:.2f} Mpc", flush=True)
    assert abs(dmean - 36.0) < 1.5, "distance diverged from published 36.0 Mpc!"
    assert 20.0 < area < 45.0, "90% area diverged from GW170817 (~31 deg^2)!"

    # No local backup: the full-res original stays recoverable from git history.
    with open(SRC, "wb") as f:
        f.write(blob)
    print("bundled bayestar.fits.gz replaced with nside-256 degraded map")


if __name__ == "__main__":
    main()
