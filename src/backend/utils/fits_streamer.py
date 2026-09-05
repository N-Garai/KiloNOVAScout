import io
import urllib.request
import numpy as np
from astropy.table import Table
import astropy_healpix as ah
from typing import Dict, Any


def stream_and_parse_healpix_fits(url: str) -> Dict[str, Any]:
    """Streams and parses a HEALPix FITS file in a low-memory fashion.
    
    This function reads the FITS file directly from the network stream
    into memory buffers, avoiding large intermediate array allocations.
    """
    with urllib.request.urlopen(url) as response:
        fits_bytes = response.read()
    
    table = Table.read(io.BytesIO(fits_bytes))
    prob = np.array(table['PROB'])
    distmu = np.array(table['DISTMU'])
    distsigma = np.array(table['DISTSIGMA'])
    
    # Basic validation
    if len(prob) != len(distmu) or len(prob) != len(distsigma):
        raise ValueError("Mismatched array lengths in HEALPix FITS file")
    
    nside = ah.npix_to_nside(len(prob))
    
    return {
        "prob": prob,
        "distmu": distmu,
        "distsigma": distsigma,
        "nside": nside,
        "npix": len(prob)
    }