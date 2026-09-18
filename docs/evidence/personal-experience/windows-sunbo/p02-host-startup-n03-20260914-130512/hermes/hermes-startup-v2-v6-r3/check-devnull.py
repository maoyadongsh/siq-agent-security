"""Read-only Windows null-device handle check, separate from Hermes runtime."""
import ctypes
import datetime
import errno
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

if sys.platform != 'win32':
    raise SystemExit('Windows only')
import msvcrt
from ctypes import wintypes

destination = Path(sys.argv[1])
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetFileType.argtypes = [wintypes.HANDLE]
kernel.GetFileType.restype = wintypes.DWORD
fd = os.open(os.devnull, os.O_RDWR)
try:
    handle_type = int(kernel.GetFileType(msvcrt.get_osfhandle(fd)))
finally:
    os.close(fd)
try:
    os.fstat(fd)
    descriptor_closed = False
except OSError as error:
    descriptor_closed = error.errno == errno.EBADF
report = {
    'schema': 'windows-null-device-handle-check/v1',
    'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'method': 'Independent workspace Python process, os.open(os.devnull, os.O_RDWR) and Win32 GetFileType',
    'python_version': platform.python_version(),
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'devnull_literal': os.devnull,
    'flags': os.O_RDWR,
    'win32_file_type': handle_type,
    'expected_character_device_type': 2,
    'descriptor_closed_verified_by_ebadf': descriptor_closed,
    'host_or_siq_executed': False,
    'scope': 'Device identity only; not a replay of any Hermes run, filesystem permission proof, or OS sandbox',
}
with destination.open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps(report))
raise SystemExit(0 if handle_type == 2 and descriptor_closed else 1)
