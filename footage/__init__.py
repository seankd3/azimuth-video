"""Azimuth Video: a local toolkit that files, describes, measures and renders camera footage."""
import os

# GPU work runs only in gpu.slice, the slice of heavy's media lane: anywhere else reclaim and swap can stall the GPU
# driver the desktop draws through. Outside it the GPU is not there, so a tool takes its CPU path.
GPU_LANE = "/gpu.slice/" in open("/proc/self/cgroup").read()
if not GPU_LANE:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""


def idle() -> None:
    """Give the desktop first claim on the CPU: every thread of this process, and every thread and child it starts
    later, runs only on CPU time nothing else wants (and so with idle disk priority too)."""
    for tid in os.listdir("/proc/self/task"):
        os.sched_setscheduler(int(tid), os.SCHED_IDLE, os.sched_param(0))
