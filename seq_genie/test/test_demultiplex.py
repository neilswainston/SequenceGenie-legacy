'''
SequenceGenie (c) University of Manchester 2018

All rights reserved.

@author: neilswainston
'''
import os
import unittest

from Bio.SeqRecord import SeqRecord

from seq_genie import demultiplex


class Test(unittest.TestCase):
    '''Class to test utils module.'''

    def test_demuliplex_simple(self):
        '''Test demuliplex method.'''
        barcodes = [('AAAAAAGGGGGG', 'AAAAAAGGGGGG')]

        directory = os.path.dirname(os.path.realpath(__file__))
        filename = os.path.join(directory, 'simple_seqs.txt')

        with open(filename) as fle:
            seqs = [SeqRecord(line.strip()) for line in fle.readlines()]

        barcode_seqs = demultiplex.demultiplex(barcodes, seqs, tolerance=1)

        self.assertEqual(len(barcode_seqs[barcodes[0]]), 2)


if __name__ == "__main__":
    unittest.main()
