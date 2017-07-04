'''
Created on 30 Jun 2017

@author: neilswainston
'''
import random
import string
import time

import multiprocessing as mp


def rand_strings(num, length, queue):
    ''''Generates a random string of lowercase chars.'''
    queue.put([''.join(random.choice(string.ascii_lowercase)
                       for _ in range(length))
               for _ in range(num)])


def main():
    '''main method.'''
    from multiprocessing import Queue
    num = 10**4
    length = 10**5
    queue = Queue()

    start = time.time()
    rand_strings(num, length, queue)
    print len(queue.get())
    end = time.time()
    print end - start

    queue = Queue()
    start = time.time()

    nprocs = mp.cpu_count()
    procs = []

    for _ in range(nprocs):
        proc = mp.Process(target=rand_strings,
                          args=(num / mp.cpu_count(), length, queue))
        proc.Daemon = True
        procs.append(proc)
        proc.start()

    results = []

    for _ in range(nprocs):
        results.extend(queue.get())

    print len(results)
    end = time.time()
    print end - start


if __name__ == '__main__':
    main()
