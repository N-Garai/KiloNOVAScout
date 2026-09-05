import io
import urllib.request
import numpy as np
import astropy_healpix as ah
from astropy.table import Table
from strands import tool
import astropy.units as u

@tool
def process_healpix_skymap(skymap_url: str) -> dict:
    """Processes HEALPix FITS skymap to extract 90% credible sky volume coordinates."""
    with urllib.request.urlopen(skymap_url) as response:
        fits_bytes = response.read()

    table = Table.read(io.BytesIO(fits_bytes))
    prob = np.array(table['PROB'])
    distmu = np.array(table['DISTMU'])
    distsigma = np.array(table['DISTSIGMA'])

    sorted_idx = np.argsort(prob)[::-1]
    cum_prob = np.cumsum(prob[sorted_idx])
    top_90_idx = sorted_idx[cum_prob <= 0.90]

    nside = ah.npix_to_nside(len(prob))
    ra, dec = ah.healpix_to_lonlat(top_90_idx, nside, order='nested')

    mean_dist = float(np.average(distmu[top_90_idx], weights=prob[top_90_idx]))
    dist_std = float(np.average(distsigma[top_90_idx], weights=prob[top_90_idx]))

    return {
        "nside": int(nside),
        "ra_min": float(np.min(ra.deg)),
        "ra_max": float(np.max(ra.deg)),
        "dec_min": float(np.min(dec.deg)),
        "dec_max": float(np.max(dec.deg)),
        "dist_mean": mean_dist,
        "dist_std": dist_std,
        "pixel_count_90": len(top_90_idx)
    }
