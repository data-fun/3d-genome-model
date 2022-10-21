""" Build 3D structure of genome with Pastis NB.

This script is a modified version of:
https://github.com/Thibault-Poinsignon/pastisnb/blob/main/scripts/generated_data/infer_structures_nb.py
by Nelle Varoqaux et Thibault Poinsignon
"""

import argparse
import numpy as np
import pandas as pd
from pathlib import Path

import iced
from iced import io
from pastis.optimization import mds
from pastis import dispersion
from pastis.optimization import negative_binomial_structure
from pastis.io.write_struct.pdb import writePDB
from scipy import sparse

def is_file(parser, file_path):
    """Check file exists.
    
    Parameters
    ----------
    parser : argparse.ArgumentParser
        Command line argument parser
    file_path : str
        File path
    Returns
    -------
    str
        File path    
    """
    if not Path(file_path).is_file():
        parser.error(f"The file {file_path} does not exist")
    else:
        return file_path


def get_cli_arguments():
    """Command line argument parser.

    Returns
    -------
    argparse.Namespace
        Object containing arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--matrix",
        action="store",
        type=lambda name: is_file(parser, name),
        help="Name of Matrix file",
        required=True,
    )
    parser.add_argument(
        "--bed",
        action="store",
        type=lambda name: is_file(parser, name),
        help="Name of Bed file",
        required=True,
    )
    parser.add_argument(
        "--output",
        action="store",
        type=str,
        help="Name of output PDB file containing the 3D structure of the genome",
        required=True,
    )
    return parser.parse_args()


def run_pastis_nb(matrix_filename, bed_filename, output_filename, seed=0, percentage_to_filter=0.02):
    """Build 3D structure of genome with Pastis NB algorithme.
    
    Parameters
    ----------
    matrix_filename : str
        Name of Matrix file
    bed_filename : str
        Name of Bed file
    output_filename : str
        Name of output PDB file with 3D structure of the genome
    seed : int (default: 0)
        Random generator seed
    percentage_to_filter : float (default: 0.02)
        Percentage to filter out data 
    """
    ###############################################################################
    #Load chromosome lengths and count data
    lengths = io.load_lengths(bed_filename)

    ###############################################################################
    # The sparse matrix generated by HiC-Pro seems to randomly miss a row.
    # The dense matrix generated by HiC-Pro_3.1.0/bin/utils/sparseToDense.py is always complete.
    # The 3D model is thus inferred from it.
    #counts = io.load_counts(matrix_filename, base=1)
    #counts_maps = pd.read_csv(matrix_filename, sep='\t', header=None)
    #counts_maps = counts_maps.values
    counts_maps = np.load(matrix_filename)
    counts_maps[np.isnan(counts_maps)] = 0
    counts = sparse.coo_matrix(counts_maps)
    counts.setdiag(0)
    counts.eliminate_zeros()
    counts = counts.tocoo()
    
    random_state = np.random.RandomState(seed)
    ###############################################################################
    # First estimate MDS for initialization
    X = mds.estimate_X(counts, random_state=random_state)
    ###############################################################################
    # Estimate constant dispersion parameters
    dispersion_ = dispersion.ExponentialDispersion(degree=0)
    _, mean, variance, weights = dispersion.compute_mean_variance(counts, lengths, bias=bias)
    dispersion_.fit(mean, variance, sample_weights=(weights**0.5))
    ###############################################################################
    # Now perform NB 3D inference.
    alpha = -3
    beta = 1
    counts = counts.tocoo()
    print("Estimating structure")
    X = negative_binomial_structure.estimate_X(
        counts, alpha, beta, bias=bias,
        lengths=lengths,
        dispersion=dispersion_,
        use_zero_entries=True,
        ini=X.flatten())
    ###############################################################################
    # Remove beads that were not infered
    mask = (np.array(counts.sum(axis=0)).flatten() + np.array(counts.sum(axis=1)).flatten() == 0)
    mask = mask.flatten()
    X_ = X.copy()
    X_[mask] = np.nan
    ###############################################################################
    np.savetxt(output_filename + ".txt", X_)
    print("Results written to", output_filename)
    writePDB(X_, output_filename)


if __name__ == "__main__":
    ARGS = get_cli_arguments()
    run_pastis_nb(
        matrix_filename=ARGS.matrix,
        bed_filename=ARGS.bed,
        output_filename=ARGS.output,
        seed=0, 
        percentage_to_filter=0.02
    )