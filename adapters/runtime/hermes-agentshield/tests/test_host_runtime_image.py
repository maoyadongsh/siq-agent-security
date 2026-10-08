"""Image-profile boundary checks; actual OpenShell probe is separate evidence."""

import importlib.util
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

adapter = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("image_guard_test", adapter / "host_runtime.py",
                                             submodule_search_locations=[str(adapter)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.getuid() == 0, reason="Linux non-root image profile")


def uninitialized_guard():
    guard = module.RuntimeGuard.__new__(module.RuntimeGuard)
    guard._image_objects = {}
    return guard


@pytest.mark.parametrize("change", [{"st_uid": 1000}, {"st_mode": stat.S_IFREG | 0o664},
                                    {"st_mode": stat.S_IFREG | 0o646}, {"st_mode": stat.S_IFLNK | 0o444},
                                    {"st_mode": stat.S_IFIFO | 0o444}])
def test_image_objects_must_be_root_owned_and_protected(change):
    fields = {"st_dev": 1, "st_ino": 2, "st_uid": 0, "st_gid": 0, "st_mode": stat.S_IFREG | 0o444}
    guard = uninitialized_guard()
    guard._protected_object("/synthetic", SimpleNamespace(**fields))
    with pytest.raises(module.RuntimeGuardError):
        guard._protected_object("/synthetic", SimpleNamespace(**(fields | change)))


@pytest.mark.parametrize("change", [{"st_ino": 3}, {"st_dev": 2}, {"st_gid": 1000},
                                    {"st_mode": stat.S_IFREG | 0o400}])
def test_replaced_or_changed_protected_object_is_not_recached(change):
    fields = {"st_dev": 1, "st_ino": 2, "st_uid": 0, "st_gid": 0, "st_mode": stat.S_IFREG | 0o444}
    guard = uninitialized_guard()
    guard._protected_object("/synthetic", SimpleNamespace(**fields))
    with pytest.raises(module.RuntimeGuardError):
        guard._protected_object("/synthetic", SimpleNamespace(**(fields | change)))


def test_runtime_walk_rejects_user_owned_ancestor_and_symlink(tmp_path):
    guard = uninitialized_guard()
    root = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    real = tmp_path / "payload"
    real.write_text("synthetic")
    real.chmod(0o444)
    link = tmp_path / "alias"
    link.symlink_to(real)
    try:
        with pytest.raises(module.RuntimeGuardError), guard._runtime_file(root, str(real), protected=True):
            pytest.fail("user-owned directory accepted")
        with pytest.raises(OSError), guard._runtime_file(root, str(link)):
            pytest.fail("symlink accepted")
    finally:
        os.close(root)


def test_runtime_walk_detects_replacement_after_read(tmp_path):
    guard = uninitialized_guard()
    path = tmp_path / "source"
    path.write_text("synthetic")
    root = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(module.RuntimeGuardError), guard._runtime_file(root, str(path)) as fd:
            assert os.read(fd, 10) == b"synthetic"
            path.rename(tmp_path / "old")
            path.write_text("synthetic")
    finally:
        os.close(root)
