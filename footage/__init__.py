"""Azimuth Video: a local toolkit that files, describes, measures and renders camera footage."""
import os


def idle() -> None:
    """Give the desktop first claim on the CPU: every thread of this process, and every thread and child it starts
    later, runs only on CPU time nothing else wants (and so with idle disk priority too)."""
    for tid in os.listdir("/proc/self/task"):
        os.sched_setscheduler(int(tid), os.SCHED_IDLE, os.sched_param(0))
