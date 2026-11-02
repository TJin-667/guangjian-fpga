"""Timing-contract demonstration only; not a device or Guangjian benchmark."""
import argparse,hashlib
from host_timing import Ledger

p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();ledger=Ledger()
with ledger.span('example_total'):
    for i in range(3):
        with ledger.span('example_memory_hash',iteration=i+1):hashlib.sha256(b'portable timing example'*1000).digest()
ledger.save(a.out,status='EXAMPLE_ONLY_NOT_HARDWARE',physical_hardware=False)
print(a.out)
