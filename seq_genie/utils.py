'''
SequenceGenie (c) University of Manchester 2018

All rights reserved.

@author: neilswainston
'''
# pylint: disable=invalid-name
# pylint: disable=no-name-in-module
# pylint: disable=too-many-arguments
from collections import defaultdict
import itertools
import os
from os.path import splitext
import subprocess
import tempfile

from Bio import Seq, SeqIO, SeqRecord
from fuzzywuzzy.fuzz import partial_ratio
from pysam import Samfile, VariantFile
from synbiochem.utils import io_utils, thread_utils

import numpy as np
import pandas as pd


def get_reads(reads_filename, min_length=0):
    '''Gets reads.'''
    reads = []

    if os.path.isdir(reads_filename):
        for dirpath, _, filenames in os.walk(os.path.abspath(reads_filename)):
            for filename in filenames:
                filename = os.path.join(dirpath, filename)
                _get_reads(filename, min_length, reads)
    else:
        _get_reads(reads_filename, min_length, reads)

    return reads


def bin_seqs(barcodes, sequences, score_threshold=90, search_len=256,
             num_threads=8):
    '''Bin sequences according to barcodes.'''
    barcode_seqs = defaultdict(list)

    max_barcode_len = max([len(barcode)
                           for pair in barcodes
                           for barcode in pair])

    if barcodes:
        thread_pool = thread_utils.ThreadPool(num_threads)

        for seq in sequences:
            thread_pool.add_task(_bin_seq, seq, max_barcode_len, search_len,
                                 score_threshold, barcodes, barcode_seqs)

        thread_pool.wait_completion()
    else:
        barcode_seqs['undefined'].extend(sequences)

    return barcode_seqs


def index(filename):
    '''Index file.'''
    subprocess.call(['bwa', 'index', filename])


def mem(templ_filename, reads_filename, out_filename=None,
        readtype='ont2d', gap_open=6):
    '''Runs BWA MEM.'''
    out_file = io_utils.get_filename(out_filename)

    with open(out_file, 'w') as out:
        subprocess.call(['bwa', 'mem',
                         '-x', readtype,
                         '-O', str(gap_open),
                         templ_filename, reads_filename],
                        stdout=out)

    return out_file


def get_vcf(bam_filename, templ_filename, pcr_offset=0):
    '''Generates a vcf file.'''
    vcf_filename = \
        tempfile.NamedTemporaryFile('w', suffix='.vcf', delete=False).name \
        if pcr_offset else bam_filename + '.vcf'

    prc = subprocess.Popen(['samtools',
                            'mpileup',
                            '-uvf',
                            templ_filename,
                            '-t', 'DP',
                            '-o', vcf_filename,
                            bam_filename])

    prc.communicate()

    if pcr_offset:
        vcf_in = VariantFile(vcf_filename)
        vcf_out = VariantFile(bam_filename + '.vcf', 'w', header=vcf_in.header)

        for rec in vcf_in.fetch():
            rec.pos = rec.pos + pcr_offset
            vcf_out.write(rec)

        vcf_out.close()

    return bam_filename + '.vcf'


def sort(in_filename, out_filename):
    '''Custom sorts SAM file.'''
    sam_file = Samfile(in_filename, 'r')
    out_file = Samfile(out_filename, 'wh',
                       template=sam_file,
                       header=sam_file.header)

    for read in sorted([read for read in sam_file],
                       key=lambda x: (-x.query_length,
                                      x.reference_start)):
        out_file.write(read)

    out_file.close()

    return out_filename


def pcr(seq, forward_primer, reverse_primer):
    '''Apply in silico PCR.'''
    for_primer_pos = seq.find(forward_primer.upper())

    rev_primer_pos = \
        seq.find(str(Seq.Seq(reverse_primer).reverse_complement().upper()))

    if for_primer_pos > -1 and rev_primer_pos > -1:
        seq = seq[for_primer_pos:] + \
            seq[:rev_primer_pos + len(reverse_primer)]
    elif for_primer_pos > -1:
        seq = seq[for_primer_pos:]
    elif rev_primer_pos > -1:
        seq = seq[:rev_primer_pos + len(reverse_primer)]

    return seq, for_primer_pos


def analyse_vcf(vcf_filename, dp_filter):
    '''Analyse vcf file, returning number of matches, mutations and indels.'''
    num_matches = 0
    mutations = []
    indels = []
    deletions = []

    df = _vcf_to_df(vcf_filename)

    for _, row in df.iterrows():
        if 'INDEL' in row:
            indels.append(row['REF'] + str(row['POS']) + row['ALT'])
        elif (dp_filter > 1 and row['DP'] > dp_filter) \
                or row['DP_PROP'] > dp_filter:
            alleles = [row['REF']] + row['ALT'].split(',')

            # Extract QS values and order to find most-likely base:
            qs = [float(val)
                  for val in dict([term.split('=')
                                   for term in row['INFO'].split(';')])
                  ['QS'].split(',')]

            # Compare most-likely base to reference:
            hi_prob_base = alleles[np.argmax(qs)]

            if row['REF'] != hi_prob_base:
                mutations.append(row['REF'] + str(row['POS']) + hi_prob_base +
                                 ' ' + str(max(qs)))
            else:
                num_matches += 1
        else:
            deletions.append(row['POS'])

    return num_matches, mutations, indels, _get_ranges_str(deletions)


def reject_indels(sam_filename, templ_seq, out_filename=None):
    '''Rejects indels.'''
    out_filename = io_utils.get_filename(out_filename)

    sam_file = Samfile(sam_filename, 'r')
    out_file = Samfile(out_filename, 'wh',
                       template=sam_file,
                       header=sam_file.header)

    for read in sam_file:
        if read.cigarstring and str(len(templ_seq)) + 'M' in read.cigarstring:
            out_file.write(read)

    out_file.close()

    return out_filename


def replace_indels(sam_filename, templ_seq, out_filename=None):
    '''Replace indels, replacing them with wildtype.'''
    out_filename = io_utils.get_filename(out_filename)

    with open(out_filename, 'w') as fle:
        SeqIO.write(_replace_indels(sam_filename, templ_seq), fle, 'fasta')

    return out_filename


def _get_reads(filename, min_length, reads):
    '''Gets reads.'''
    _, ext = splitext(filename)

    try:
        with open(filename, 'rU') as fle:
            reads.extend([record
                          for record in SeqIO.parse(fle, ext[1:])
                          if len(record.seq) > min_length])
    except (IOError, ValueError), err:
        print err


def _bin_seq(seq, max_barcode_len, search_len, score_threshold, barcodes,
             barcode_seqs):
    '''Bin an individual sequence.'''
    trim_seq_start = seq.seq[:max_barcode_len + search_len]
    trim_seq_end = seq.seq[-(max_barcode_len + search_len):]

    max_scores = score_threshold, score_threshold
    selected_barcodes = None

    for pair in barcodes:
        scores_forw = partial_ratio(pair[0], trim_seq_start), \
            partial_ratio(pair[1], trim_seq_end.reverse_complement())

        scores_rev = partial_ratio(pair[1], trim_seq_start), \
            partial_ratio(pair[0], trim_seq_end.reverse_complement())

        if scores_forw[0] > max_scores[0] and scores_forw[1] > max_scores[1]:
            selected_barcodes = pair
            max_scores = scores_forw

        if scores_rev[0] > max_scores[0] and scores_rev[1] > max_scores[1]:
            selected_barcodes = pair
            max_scores = scores_rev

    if selected_barcodes:
        barcode_seqs[selected_barcodes].append(seq)


def _vcf_to_df(vcf_filename):
    '''Convert vcf to Pandas dataframe.'''
    data = []

    with open(vcf_filename) as vcf:
        for line in vcf:
            if line.startswith('##'):
                pass
            elif line.startswith('#'):
                columns = line[1:].split()[:-1] + ['DATA']
            else:
                data.append(line.split())

    df = _expand_info(pd.DataFrame(columns=columns, data=data))

    df['POS'] = df['POS'].astype(int)

    if 'DP' in df.columns:
        df['DP'] = df['DP'].astype(int)
        df['DP_PROP'] = df['DP'] / df['DP'].max()

    if 'INDEL' in df.columns:
        df[['INDEL']] = df[['INDEL']].fillna(value=False)

    return df


def _expand_info(df):
    '''Expand out INFO column from vcf file.'''
    infos = []

    for row in df.itertuples():
        info = [term.split('=') for term in row.INFO.split(';')]

        infos.append({term[0]: (term[1] if len(term) == 2 else True)
                      for term in info})

    return df.join(pd.DataFrame(infos, index=df.index))


def _replace_indels(sam_filename, templ_seq):
    '''Replace indels, replacing them with wildtype.'''
    sam_file = Samfile(sam_filename, 'r')

    for read in sam_file:
        # Perform mapping of nucl indices to remove spurious indels:
        seq = ''.join([read.seq[pair[0]]
                       if pair[0]
                       else templ_seq[pair[1]]
                       for pair in read.aligned_pairs
                       if pair[1] is not None])

        if seq:
            yield SeqRecord.SeqRecord(Seq.Seq(seq), read.qname, '', '')


def _get_ranges_str(vals):
    '''Convert list of integers to range strings.'''
    return ['-'.join([str(r) for r in rnge])
            if rnge[0] != rnge[1]
            else rnge[0]
            for rnge in _get_ranges(vals)]


def _get_ranges(vals):
    '''Convert list of integer to ranges.'''
    ranges = []

    for _, b in itertools.groupby(enumerate(vals), lambda (x, y): y - x):
        b = list(b)
        ranges.append((b[0][1], b[-1][1]))

    return ranges
