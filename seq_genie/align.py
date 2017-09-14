'''
DNA++ (c) DNA++ 2017

All rights reserved.

@author: neilswainston
'''
# pylint: disable=no-member
# pylint: disable=ungrouped-imports
# pylint: disable=too-few-public-methods
from collections import defaultdict
import subprocess
import sys

from Bio import SeqIO, Seq, SeqRecord
from pysam import bcftools
import pysam

from seq_genie import utils
from synbiochem.utils import io_utils, seq_utils


class Aligner(object):
    '''Class to align reads to a reference.'''

    def __init__(self, templ_filename):
        self.__templ_filename = templ_filename

        with open(self.__templ_filename, 'rU') as fle:
            self.__templ_seq = [str(record.seq)
                                for record in SeqIO.parse(fle, 'fasta')][0]

        # Index template:
        subprocess.call(['bwa', 'index', self.__templ_filename])

    def align(self, seqs_filename):
        '''Aligns sequences in barcoded bins.'''
        # Read sequences:
        with open(seqs_filename, 'rU') as fle:
            seqs = {record.id: str(record.seq)
                    for record in SeqIO.parse(fle, 'fasta')}

        # Align and sort:
        utils.sort(self.__mem(seqs), 'align.sam')

    def __align(self, barcode, id_seqs):
        '''Aligns sequences in a given bin.'''

        # Align, sort and strip indels from file:
        fasta_strip_filename = \
            self.__strip_indels(utils.sort(self.__mem(id_seqs)))

        strip_id_seqs = seq_utils.read_fasta(fasta_strip_filename)

        # Align strip indels:
        utils.sort(self.__mem(strip_id_seqs), barcode + '.sam')

        # Translate strip indels:
        _translate(strip_id_seqs, barcode + '_aa.fasta')

    def __strip_indels(self, in_filename, out_filename=None):
        '''Strips spurious indels.'''
        out_filename = io_utils.get_filename(out_filename)

        with open(out_filename, 'w') as fle:
            SeqIO.write(self.__sam_to_rec(in_filename), fle, 'fasta')

        return out_filename

    def __sam_to_rec(self, in_filename):
        '''Generator to convert sam files into Biopython SeqRecords.'''
        sam_file = pysam.Samfile(in_filename, 'r')

        for read in sam_file:
            # Perform mapping of nucl indices to remove spurious indels:
            seq = ''.join([read.seq[pair[0]]
                           if pair[0]
                           else self.__templ_seq[pair[1]]
                           for pair in read.aligned_pairs
                           if pair[1] is not None])

            if seq:
                yield SeqRecord.SeqRecord(Seq.Seq(seq), read.qname, '', '')


def _bin_seqs(barcodes, sequences, evalue=0.1):
    '''Bin sequences according to barcodes.'''
    seq_bin = defaultdict(dict)

    if barcodes:
        results = seq_utils.do_blast(barcodes, sequences, evalue=evalue,
                                     word_size=4)

        for result in results:
            barcode = 'undefined'
            # expect = float('NaN')

            for alignment in result.alignments:
                barcode = alignment.hit_def
                # expect = alignment.hsps[0].expect
                break

            seq_bin[barcode][result.query] = sequences[result.query]
    else:
        seq_bin['undefined'] = {seq_id: seq
                                for seq_id, seq in sequences.iteritems()}

    return seq_bin


def _convert(sam_filename, bam_filename=None):
    '''Convert SAM file to BAM file.'''
    bam_filename = io_utils.get_filename(bam_filename)

    with open(bam_filename, 'w') as bam_file:
        bam_file.write(pysam.view('-b', sam_filename))

    return bam_filename


def _mpileup(in_filename, templ_filename, out_filename=None):
    '''Runs mpileup.'''
    out_filename = io_utils.get_filename(out_filename)

    with open(out_filename, 'w') as out_file:
        out_file.write(pysam.mpileup('-uvBAd', '500000',
                                     '-f', templ_filename,
                                     in_filename))
    return out_filename


def _call(in_filename, out_filename=None):
    '''Runs call.'''
    out_filename = io_utils.get_filename(out_filename)

    with open(out_filename, 'w') as out_file:
        out_file.write(bcftools.call('-vcO', 'v',
                                     in_filename))
    return out_filename


def _filter(in_filename, min_qual=10, max_vdb=1e-12, out_filename=None):
    '''Runs filter.'''
    out_filename = io_utils.get_filename(out_filename)

    with open(out_filename, 'w') as out_file:
        out_file.write(bcftools.filter('-O', 'v',
                                             '-i%QUAL>' + str(min_qual) +
                                             ' && VDB<' + str(max_vdb),
                                             in_filename))
    return out_filename


def _translate(id_seqs, out_filename):
    '''Translate nucleotide seqs to aa seqs.'''
    out_filename = io_utils.get_filename(out_filename)

    with open(out_filename, 'w') as fle:
        for seq_id, seq in id_seqs.iteritems():
            rec = SeqRecord.SeqRecord(Seq.Seq(seq).translate(), seq_id, '', '')
            SeqIO.write(rec, fle, 'fasta')

    return out_filename


def main(args):
    '''main method.'''
    aligner = Aligner(args[0])

    # seq_filter = args[2] if len(args) > 2 else None
    # barcodes = {value: value for value in args[3:]} \
    #    if len(args) > 3 else None
    aligner.align(args[1])


if __name__ == '__main__':
    main(sys.argv[1:])
