'''
SequenceGenie (c) University of Manchester 2018

All rights reserved.

@author: neilswainston
'''
# pylint: disable=invalid-name
# pylint: disable=no-name-in-module
# pylint: disable=superfluous-parens
import os
import subprocess
import tempfile

from Bio import Seq, SeqIO, SeqRecord
from pysam import Samfile, VariantFile
from synbiochem.utils import io_utils


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
        if pcr_offset else os.path.join(os.path.dirname(bam_filename),
                                        'variants.vcf')

    prc = subprocess.Popen(['samtools',
                            'mpileup',
                            '-uvf',
                            templ_filename,
                            '-t', 'DP',
                            '-o', vcf_filename,
                            bam_filename])

    prc.communicate()

    if pcr_offset:
        vcf_out_filename = os.path.join(os.path.dirname(bam_filename),
                                        'variants.vcf')
        vcf_in = VariantFile(vcf_filename)
        vcf_out = VariantFile(vcf_out_filename, 'w', header=vcf_in.header)

        for rec in vcf_in.fetch():
            rec.pos = rec.pos + pcr_offset
            print(rec)
            vcf_out.write(rec)

        vcf_out.close()
        return vcf_out_filename

    return vcf_filename


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


def reject_indels(sam_filename_in, templ_filename, sam_filename_out):
    '''Rejects indels.'''
    sam_file = Samfile(sam_filename_in, 'r')
    out_file = Samfile(sam_filename_out, 'wh',
                       template=sam_file,
                       header=sam_file.header)
    templ_seq = get_seq(templ_filename)

    for read in sam_file:
        if read.cigarstring and str(len(templ_seq)) + 'M' in read.cigarstring:
            out_file.write(read)

    out_file.close()


def replace_indels(sam_filename_in, templ_filename, sam_filename_out):
    '''Replace indels, replacing them with wildtype.'''
    sam_filename_out = io_utils.get_filename(sam_filename_out)
    templ_seq = get_seq(templ_filename)
    records = []

    for read in Samfile(sam_filename_in, 'r'):
        # Perform mapping of nucl indices to remove spurious indels:
        seq = ''.join([read.seq[pair[0]]
                       if pair[0]
                       else templ_seq[pair[1]]
                       for pair in read.aligned_pairs
                       if pair[1] is not None])

        if seq:
            records.append(SeqRecord.SeqRecord(Seq.Seq(seq), read.qname,
                                               '', ''))

    reads_filename = io_utils.get_filename(None)

    with open(reads_filename, 'w') as fle:
        SeqIO.write(records, fle, 'fasta')

    mem(templ_filename, reads_filename,
        out_filename=sam_filename_out,
        gap_open=12)

    return sam_filename_out


def get_dir(parent_dir, barcodes, ice_id=None):
    '''Get directory from barcodes.'''
    dir_name = os.path.join(parent_dir, '_'.join(barcodes))

    if ice_id:
        dir_name = os.path.join(dir_name, ice_id)

    if not os.path.exists(dir_name):
        os.makedirs(dir_name)

    return dir_name


def get_seq(filename):
    '''Get sequence from Fasta file.'''
    for record in SeqIO.parse(filename, 'fasta'):
        return record.seq

    return None
