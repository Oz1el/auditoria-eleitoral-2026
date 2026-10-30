"""Bounded read-only processes; only the parent publishes audit results."""
from __future__ import annotations
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import os
from pathlib import Path
import zipfile

TASK_SIZE=32
MAX_PENDING=8
_ARCHIVE=None
_NAMES=None
_STAGES=None
_CRYPTO=True
_RECOVERY=None


def physical_cpus():
    selected=[];seen=set()
    for cpu in sorted(os.sched_getaffinity(0)):
        topology=Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        key=((topology/'physical_package_id').read_text(),(topology/'core_id').read_text())
        if key not in seen:selected.append(cpu);seen.add(key)
    return selected


def worker_cpus(workers):
    if workers not in (1,2,4):raise ValueError('workers must be 1, 2 or 4')
    available=physical_cpus()
    if len(available)<workers:raise ValueError('not enough distinct physical CPU cores')
    return available[:workers]


def _initialize(path,stages,crypto,recovery,cpus):
    global _ARCHIVE,_NAMES,_STAGES,_CRYPTO,_RECOVERY
    os.sched_setaffinity(0,{cpus.get(timeout=30)})
    _ARCHIVE=zipfile.ZipFile(path);names=_ARCHIVE.namelist()
    if len(names)!=len(set(names)):raise ValueError('duplicate raw archive members')
    _NAMES=set(names);_STAGES=stages;_CRYPTO=crypto;_RECOVERY=recovery
    from .common import emit
    emit('complement_worker_started',pid=os.getpid(),physical_cpu_id=next(iter(os.sched_getaffinity(0))))


def _section_chunk(rows):
    from .complement import section_result
    results=[]
    for section in rows:
        recovery=_RECOVERY if section['uf']=='SP' and (section['municipio'],section['zona'],section['secao'])==(64777,395,298) else None
        results.append(section_result(section,_ARCHIVE,_NAMES,_STAGES,crypto=_CRYPTO,recovered=recovery))
    return results


def ordered_bounded(pool,function,chunks,max_pending=MAX_PENDING):
    """At most eight chunks may be submitted; yield original order even on skew."""
    iterator=iter(chunks);pending=deque()
    try:
        for _ in range(max_pending):
            chunk=next(iterator,None)
            if chunk is None:break
            pending.append(pool.submit(function,chunk))
        while pending:
            yield pending.popleft().result()
            chunk=next(iterator,None)
            if chunk is not None:pending.append(pool.submit(function,chunk))
    finally:
        for future in pending:future.cancel()


def parallel_sections(rows,path,stages,*,workers=4,crypto=True,recovery=None):
    """Separate ZIP per worker; bounded IPC; no worker writes or checkpoints."""
    cpus=worker_cpus(workers)
    for name in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[name]='1'
    ctx=mp.get_context('spawn');queue=ctx.Queue()
    for cpu in cpus:queue.put(cpu)
    pool=ProcessPoolExecutor(max_workers=workers,mp_context=ctx,initializer=_initialize,
                             initargs=(str(path),stages,crypto,recovery,queue))
    try:
        chunks=(rows[i:i+TASK_SIZE] for i in range(0,len(rows),TASK_SIZE))
        for result in ordered_bounded(pool,_section_chunk,chunks):
            yield from result
    finally:
        pool.shutdown(wait=True,cancel_futures=True)
        queue.close();queue.join_thread()
