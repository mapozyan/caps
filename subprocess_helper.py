import os
import platform
import subprocess

SUBPROCESS_CREATION_FLAGS = {
    'Linux':   0,
    'Darwin':  0,
    'Windows': 0x00000008 # DETACHED_PROCESS
}

FNULL = open(os.devnull, 'w')

def _get_creation_flags():
    os_name = platform.system()
    return SUBPROCESS_CREATION_FLAGS[os_name]

def subprocess_call(cmdline):

    return subprocess.call(cmdline, stdout=FNULL, stderr=FNULL, creationflags=_get_creation_flags())

def subprocess_popen(cmdline):

    return subprocess.Popen(cmdline, stdout=FNULL, stderr=FNULL, creationflags=_get_creation_flags())
