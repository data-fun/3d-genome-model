"""Detect flipped contigs from a PDB file containing a 3D genome structure.

Invert the flipped part of the genome in the 3D structure and the sequence.

This script requires:
- a PDB file containing the 3D genome structure,
- a fasta file containing the genome sequence,
- an Hi-C resolution.
"""

import argparse
import math
import sys

from Bio import SeqIO
from Bio.Seq import Seq
from biopandas.pdb import PandasPdb
import numpy as np
import pandas as pd


def get_cli_arguments():
    """Command line argument parser.

    Returns
    -------
    argparse.Namespace
        Object containing arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pdb",
        action="store",
        type=str,
        help="PDB file containing the 3D structure of the genome",
        required=True,
    )
    parser.add_argument(
        "--fasta",
        action="store",
        type=str,
        help="Fasta file containing the sequence of the genome",
        required=True,
    )
    parser.add_argument(
        "--resolution",
        action="store",
        type=int,
        help="HiC resolution",
        required=True,
    )
    parser.add_argument(
        "--output-pdb",
        action="store",
        type=str,
        help="Output PDB file containing the fixed 3D structure of the genome",
        required=True,
    )
    parser.add_argument(
        "--output-fasta",
        action="store",
        type=str,
        help="Output FASTA file containing the fixed sequence of the genome",
        required=True,
    )
    parser.add_argument(
        "--threshold",
        action="store",
        type=float,
        help="Threshold to detect flipped contigs",
        required=False,
        default=3.0
    )
    return parser.parse_args()


def extract_chromosome_name_length(fasta_name):
    """Extract chromosome name and length from a FASTA file.

    Parameters
    ----------
    fasta_name : str
        Name of Fasta file containing the sequence of the genome
    
    Returns
    -------
    tuple
        List of chromosome names
        List of chromosome lengthes
    """
    chromosome_name_lst = []
    chromosome_length_lst = []
    with open(fasta_name, "r") as fasta_file:
        print(f"Reading {fasta_name}")
        for record in SeqIO.parse(fasta_file, "fasta"):
            name = record.id
            length = len(record.seq)
            print(f"Found chromosome {name} with {length} bases")
            chromosome_name_lst.append(name)
            chromosome_length_lst.append(length)
    return chromosome_name_lst, chromosome_length_lst


def compute_bead_distances(atom_array):
    """Compute distance between beads.

    Parameters
    ----------
    atom_array : numpy.ndarray
        Array containing beads coordinates. Array dimensions are (n, 3).
    
    Returns
    -------
    numpy.ndarray
        Distance between beads as 1D-array.
    """
    distances = np.sqrt( (np.diff(atom_array[:, 0], axis=0))**2
                       + (np.diff(atom_array[:, 1], axis=0))**2
                       + (np.diff(atom_array[:, 2], axis=0))**2
                       )
    distances = np.append(distances, [0])
    return distances


def find_inverted_contigs(pdb_name_in, chromosome_length, HiC_resolution, threshold):
    """Detect inverted contigs.

    It uses the eucledian distance between adjacent beads in the 3D structure of the genome.

    Parameters
    ----------
    pdb_name_in : str
        PDB file containing the 3D structure of the genome
    chromosome_length : list
        List with chromosome lengths
    HiC_resolution : int
        HiC resolution
    threshold : float
        Threshold to detect flipped contigs
    
    Returns
    -------
    inverted_contigs : dict
        Dictionnary with inverted contigs
    """
    pdb_structure = PandasPdb().read_pdb(pdb_name_in)
    structure_df = pdb_structure.df["ATOM"]
    print(f"Number of beads read from structure: {structure_df.shape[0]}")

    if structure_df["residue_number"].isna().sum() > 0:
        print(structure_df["residue_number"].isna().sum())
        sys.exit(f"Cannot process structure {pdb_name_in} because it contains missing residue numbers (chromosomes)")

    beads_per_chromosome = [math.ceil(length/HiC_resolution) for length in chromosome_length]
    print(f"Number of expected beads deduced from sequence and HiC resolution: {sum(beads_per_chromosome)}")

    if structure_df.shape[0] != sum(beads_per_chromosome):
        sys.exit(f"Cannot process structure {pdb_name_in} because it contains {structure_df.shape[0]} beads instead of {sum(beads_per_chromosome)}")
    
    inverted_contigs = {}

    for chrom_index in structure_df["residue_number"].unique():
        print(f"\nLooking for inverted contigs into chromosome {chrom_index}")
        
        # Select beads of one chromosome
        chromosome_df = structure_df.query(f"residue_number == {chrom_index}").reset_index(drop=True)
                
        # Compute Euclidean distances between bead n and bead n+1
        coordinates = chromosome_df[["x_coord", "y_coord", "z_coord"]].to_numpy()
        euclidean_distances = compute_bead_distances(coordinates)
        median_distance = np.median(euclidean_distances)
        print(f"Median distance between beads: {median_distance:.2f}")
        
        # Select extremities of inverted contigs
        # i.e. beads with distance above a given threshold of 3*mean(distances)
        chromosome_df = chromosome_df.assign(distance = euclidean_distances)
        # Output beads coordinates with distance
        chromosome_df.to_csv(f"chr_{chrom_index}.tsv", sep="\t", index=False)
        beads_selection = chromosome_df["distance"] > threshold * median_distance
        inversion_limits = chromosome_df.loc[beads_selection , "atom_number"].values
        if len(inversion_limits)%2 != 0:
            print("WARNING: odd number of inversion limits found")
            print("WARNING: this might lead to a wrong detection of inverted contigs")
            print(inversion_limits)
        if len(inversion_limits) != 0:
            for limit_1, limit_2 in zip(inversion_limits[0::2], inversion_limits[1::2]):
                print(f"Chromosome {chrom_index}: found inverted contig between bead {limit_1+1} and bead {limit_2}")
                if chrom_index in inverted_contigs:
                    inverted_contigs[chrom_index].append((limit_1+1, limit_2))
                else:
                    inverted_contigs[chrom_index] = [(limit_1+1, limit_2)]
        else:
            inverted_contigs[chrom_index] = []
        return inverted_contigs


def flip_inverted_contigs_in_structure(inverted_contigs, pdb_name_in, pdb_name_out):
    """Flip inverted contigs in the 3D structure of the genome.

    Parameters
    ----------
    inverted_contigs : dict
        Dictionnary with inverted contigs
    pdb_name_in : str
        PDB file containing the 3D structure of the genome
    pdb_name_out : str
        Output PDB file containing the 3D structure of the genome
    """
    pdb_structure = PandasPdb().read_pdb(pdb_name_in)
    coordinates = pdb_structure.df["ATOM"]
    print(f"Number of beads read from structure: {coordinates.shape[0]}")

    for chrom_num in inverted_contigs:
        for contig in inverted_contigs[chrom_num]:
            contig_start, contig_end = contig
            print(f"Structure of chromosome {chrom_num}: "
                  f"flip contig between beads {contig_start} "
                  f"and {contig_end}")
            contig_start_index = coordinates[ (coordinates["residue_number"]==chrom_num) 
                                            & (coordinates["atom_number"]==contig_start)
                                            ].index[0]
            contig_end_index = coordinates[ (coordinates["residue_number"]==chrom_num) 
                                            & (coordinates["atom_number"]==contig_end)
                                            ].index[0]
            contig_before_df = coordinates.loc[:contig_start_index-1, :]
            contig_df = coordinates.loc[contig_start_index:contig_end_index, :]
            contig_after_df = coordinates.loc[contig_end_index+1:, :]
            # Flip contig.
            contig_df = contig_df[::-1]
            # Assemble genome structure.
            coordinates = pd.concat([contig_before_df, contig_df, contig_after_df])

    
    coordinates = coordinates.reset_index(drop=True)
    # The 'line_idx' column keeps the real order of atoms in the PDB file.
    coordinates["line_idx"] = coordinates.index
    pdb_structure.df["ATOM"] = coordinates
    pdb_structure.to_pdb(path=pdb_name_out, records=None, gz=False, append_newline=True)


def flip_inverted_contigs_in_sequence(inverted_contigs, chromosome_names, fasta_name_in, HiC_resolution, fasta_name_out):
    """Flip inverted contigs in the genome 3D structure and sequence.

    Parameters
    ----------
    inverted_contigs : dict
        Dictionnary with inverted contigs
    chromosome_names : list
        List with chromosome names
    fasta_name_in : str
        Name of Fasta file containing the sequence of the genome
    HiC_resolution : int
        HiC resolution
    fasta_name_out : str
        Output FASTA file containing the corrected sequence (at the 3D structure resolution!)
    """
    # Flip inverted contigs in the genome sequence.
    genome_fasta = SeqIO.to_dict(SeqIO.parse(fasta_name_in, "fasta"))
    
    for chrom_num in inverted_contigs:
        chrom_name = chromosome_names[chrom_num-1]
        chrom_sequence = str(genome_fasta[chrom_name].seq)
        for contig in inverted_contigs[chrom_num]:
            contig_start = contig[0] * HiC_resolution
            contig_end = contig[1] * HiC_resolution
            print(f"Sequence of chromosome {chrom_num}: "
                  f"flip inverted contig between base {contig_start} "
                  f"and {contig_end}")
            contig_sequence = chrom_sequence[contig_start:contig_end+1]
            # Flip contig.
            contig_sequence = contig_sequence[::-1]
            # Reassemble chromosome sequence.
            chrom_sequence = chrom_sequence[:contig_start] + contig_sequence + chrom_sequence[contig_end+1:]
        genome_fasta[chrom_name].seq = Seq(chrom_sequence)
  
    # Write sequence.
    with open(fasta_name_out, "w") as fasta_file:
        SeqIO.write(genome_fasta.values(), fasta_file, "fasta")

    
if __name__ == "__main__":
    ARGS = get_cli_arguments()

    # Read Fasta file and extract chromosome name and length
    CHROMOSOME_NAMES, CHROMOSOME_LENGTHS = extract_chromosome_name_length(ARGS.fasta)

    # Find inverted contigs.
    INVERTED_CONTIGS = find_inverted_contigs(ARGS.pdb, CHROMOSOME_LENGTHS, ARGS.resolution, ARGS.threshold)
    # Flip inverted contigs in the genome 3D structure and sequence.
    flip_inverted_contigs_in_structure(INVERTED_CONTIGS, ARGS.pdb, ARGS.output_pdb)
    flip_inverted_contigs_in_sequence(INVERTED_CONTIGS, CHROMOSOME_NAMES, ARGS.fasta, ARGS.resolution, ARGS.output_fasta)

