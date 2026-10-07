"""Real file reads, source drift, cache attacks and observer failure boundaries."""

import concurrent.futures
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("siq_native_source", Path(__file__).parents[1] / "native_source.py")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux native loader profile")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def skill(tmp_path):
    main = tmp_path / "approved" / "SKILL.md"
    main.parent.mkdir()
    main.write_bytes(b"---\nname: synthetic\n---\nSynthetic task.\n")
    return main


def assert_poisoned(reader, main):
    with pytest.raises(source.SourceError, match="^native_skill_source_unavailable$"):
        reader.read(main)


@pytest.mark.parametrize("raw", [b"", b"ordinary text", b"\xef\xbb\xbfBOM\r\nnext\rend\n",
                                  b"bad: \xff\xfe\x00", "中文 😀\r\n".encode(), b"x" * source.MAX_BYTES])
def test_same_bytes_hash_and_text_match_real_hermes_decode(skill, raw):
    skill.write_bytes(raw)
    events = []
    reader = source.SkillSourceReader(events.append)
    text = reader.read(skill)
    assert text == skill.read_text(encoding="utf-8-sig", errors="replace")
    assert events == [{"schema_version": "native-skill-source/v1",
                       "skill_file": {"path_sha256": sha(str(skill).encode()), "sha256": sha(raw), "bytes": len(raw)},
                       "content_file": {"path_sha256": sha(str(skill).encode()), "sha256": sha(raw), "bytes": len(raw)},
                       "text_sha256": sha(text.encode()),
                       "decoding": "utf-8-sig-replace-universal-newlines/v1", "cache_hit": False}]
    assert str(skill) not in json.dumps(events)
    assert "Synthetic task." not in json.dumps(events)


def test_main_and_support_bytes_are_distinct_and_both_rechecked_on_cache(skill):
    support = skill.parent / "reference.md"
    support.write_text("Only a reference")
    events = []
    reader = source.SkillSourceReader(events.append)
    assert reader.read(skill, support) == "Only a reference"
    assert reader.read(skill, support, cache_hit=True) == "Only a reference"
    assert len(events) == 2 and events[1]["cache_hit"] is True
    assert events[0]["skill_file"]["sha256"] == sha(skill.read_bytes())
    assert events[0]["content_file"]["sha256"] == sha(support.read_bytes())
    skill.write_text("Changed approved main")
    with pytest.raises(source.SourceError):
        reader.read(skill, support, cache_hit=True)
    assert len(events) == 2
    assert_poisoned(reader, skill)


@pytest.mark.parametrize("cached", [False, True])
def test_same_size_and_restored_mtime_cannot_hide_changed_content(skill, cached):
    events = []
    reader = source.SkillSourceReader(events.append)
    reader.read(skill)
    before = skill.stat()
    original = skill.read_bytes()
    skill.write_bytes(b"x" * len(original))
    os.utime(skill, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert skill.stat().st_size == before.st_size
    assert skill.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(source.SourceError):
        reader.read(skill, cache_hit=cached)
    assert len(events) == 1
    skill.write_bytes(original)
    assert_poisoned(reader, skill)


def test_cache_cannot_claim_a_file_never_delivered(skill):
    events = []
    reader = source.SkillSourceReader(events.append)
    with pytest.raises(source.SourceError):
        reader.read(skill, cache_hit=True)
    assert events == []
    assert_poisoned(reader, skill)


def test_main_read_does_not_make_support_cache_hit_valid(skill):
    events = []
    reader = source.SkillSourceReader(events.append)
    reader.read(skill)
    support = skill.parent / "reference.md"
    support.write_text("reference")
    with pytest.raises(source.SourceError):
        reader.read(skill, support, cache_hit=True)
    assert len(events) == 1


@pytest.mark.parametrize("kind", ["file_symlink", "parent_symlink", "hardlink", "directory", "fifo", "oversize"])
def test_unsafe_real_files_fail_before_observation(skill, tmp_path, kind):
    if kind == "file_symlink":
        target = skill.with_name("real.md")
        skill.rename(target)
        skill.symlink_to(target)
    elif kind == "parent_symlink":
        link = tmp_path / "alias"
        link.symlink_to(skill.parent, target_is_directory=True)
        skill = link / "SKILL.md"
    elif kind == "hardlink":
        os.link(skill, skill.with_name("alias.md"))
    elif kind == "directory":
        skill.unlink()
        skill.mkdir()
    elif kind == "fifo":
        skill.unlink()
        os.mkfifo(skill)
    else:
        skill.write_bytes(b"x" * (source.MAX_BYTES + 1))
    events = []
    reader = source.SkillSourceReader(events.append)
    with pytest.raises(source.SourceError, match="^native_skill_source_unavailable$"):
        reader.read(skill)
    assert events == []
    assert_poisoned(reader, skill)


@pytest.mark.parametrize("kind", ["relative", "dotdot", "dot", "double_slash", "nul", "surrogate",
                                  "long_path", "deep_path", "wrong_main", "outside", "bool_cache"])
def test_invalid_input_rejected_without_observation(skill, tmp_path, kind):
    main, other, cached = str(skill), None, False
    if kind == "relative":
        main = "SKILL.md"
    elif kind == "dotdot":
        main = str(skill.parent) + "/../approved/SKILL.md"
    elif kind == "dot":
        main = str(skill.parent) + "/./SKILL.md"
    elif kind == "double_slash":
        main = "/" + main
    elif kind == "nul":
        main += "\0"
    elif kind == "surrogate":
        main += "\ud800"
    elif kind == "long_path":
        main = "/" + "中" * 1400 + "/SKILL.md"
    elif kind == "deep_path":
        main = "/a" * 128 + "/SKILL.md"
    elif kind == "wrong_main":
        main = str(skill.with_name("other.md"))
    elif kind == "outside":
        other = str(tmp_path / "outside.md")
    else:
        cached = 1
    events = []
    reader = source.SkillSourceReader(events.append)
    with pytest.raises(source.SourceError):
        reader.read(main, other, cache_hit=cached)
    assert events == []
    assert_poisoned(reader, skill)


@pytest.mark.parametrize("change", ["overwrite", "replace", "parent_replace", "symlink_replace"])
def test_file_or_ancestor_replacement_during_observer_returns_no_text(skill, change):
    original = skill.read_bytes()

    def observer(_):
        if change == "overwrite":
            skill.write_bytes(b"x" * len(original))
        elif change == "replace":
            skill.unlink()
            skill.write_bytes(original)
        elif change == "parent_replace":
            skill.parent.rename(skill.parent.with_name("moved"))
            skill.parent.mkdir()
            skill.write_bytes(original)
        else:
            skill.rename(skill.with_name("moved.md"))
            skill.symlink_to(skill.with_name("moved.md"))

    reader = source.SkillSourceReader(observer)
    with pytest.raises(source.SourceError):
        reader.read(skill)
    assert_poisoned(reader, skill)


@pytest.mark.parametrize("outcome", ["exception", "allow", "close", "reenter"])
def test_observer_is_mandatory_and_cannot_authorize_or_erase_failure(skill, outcome):
    def observer(_):
        if outcome == "exception":
            raise RuntimeError("PRIVATE_CONTENT_MUST_NOT_APPEAR")
        if outcome == "allow":
            return {"allow": True}
        if outcome == "close":
            reader.close()
        if outcome == "reenter":
            with pytest.raises(source.SourceError):
                reader.read(skill)
        return None

    reader = source.SkillSourceReader(observer)
    with pytest.raises(source.SourceError, match="^native_skill_source_unavailable$"):
        reader.read(skill)
    assert_poisoned(reader, skill)


def test_observer_cannot_mutate_pinned_metadata(skill):
    def observer(event):
        event["skill_file"]["sha256"] = "0" * 64
        event["content_file"].clear()

    reader = source.SkillSourceReader(observer)
    expected = reader.read(skill)
    assert reader.read(skill, cache_hit=True) == expected


def test_forked_process_fails_before_inherited_lock(skill):
    reader = source.SkillSourceReader(lambda _: None)
    pid = os.fork()
    if pid == 0:
        try:
            reader.read(skill)
        except source.SourceError:
            os._exit(0)
        except BaseException:  # noqa: BLE001 - child must exit, not resume the test runner
            os._exit(2)
        os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert reader.read(skill) == skill.read_text()


def test_source_budget_has_no_eviction_to_erase_lineage(skill, monkeypatch):
    # Small limit exercises the exact full-reader path without hundreds of files.
    monkeypatch.setattr(source, "MAX_SOURCES", 2)
    events = []
    reader = source.SkillSourceReader(events.append)
    reader.read(skill)
    for name in ("a.md", "b.md"):
        skill.with_name(name).write_text(name)
    reader.read(skill, skill.with_name("a.md"))
    with pytest.raises(source.SourceError):
        reader.read(skill, skill.with_name("b.md"))
    assert len(events) == 2
    assert_poisoned(reader, skill)


def test_repeated_errors_close_all_file_descriptors(skill):
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(20):
        def observer(_):
            raise RuntimeError("expected")
        with pytest.raises(source.SourceError):
            source.SkillSourceReader(observer).read(skill)
    assert len(os.listdir("/proc/self/fd")) == before


def test_concurrent_same_task_reads_are_serialized_and_observed(skill):
    events = []
    reader = source.SkillSourceReader(events.append)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        texts = list(pool.map(lambda _: reader.read(skill), range(8)))
    assert texts == [skill.read_text()] * 8
    assert len(events) == 8
    reader.close()
    assert_poisoned(reader, skill)


def test_text_with_inline_shell_is_never_executed(skill, tmp_path):
    marker = tmp_path / "MUST_NOT_EXIST"
    text = f"!`touch {marker}`\n$(touch {marker})\n{{{{ template }}}}\n"
    skill.write_text(text)
    assert source.SkillSourceReader(lambda _: None).read(skill) == text
    assert not marker.exists()


def test_no_observer_and_missing_os_capability_reject(monkeypatch):
    with pytest.raises(source.SourceError):
        source.SkillSourceReader(None)
    monkeypatch.delattr(source.os, "O_NOFOLLOW")
    with pytest.raises(source.SourceError):
        source.SkillSourceReader(lambda _: None)


def test_file_mutation_during_read_never_reaches_observer(skill, monkeypatch):
    events = []
    original_read = source.os.read
    changed = False

    def read_then_mutate(fd, size):
        nonlocal changed
        raw = original_read(fd, size)
        if not changed:
            changed = True
            skill.write_bytes(b"x" * skill.stat().st_size)
        return raw

    monkeypatch.setattr(source.os, "read", read_then_mutate)
    with pytest.raises(source.SourceError):
        source.SkillSourceReader(events.append).read(skill)
    assert changed and events == []


def test_short_reads_still_hash_and_deliver_the_complete_file(skill, monkeypatch):
    original_read = source.os.read
    monkeypatch.setattr(source.os, "read", lambda fd, size: original_read(fd, min(3, size)))
    events = []
    assert source.SkillSourceReader(events.append).read(skill) == skill.read_text()
    assert events[0]["skill_file"]["sha256"] == sha(skill.read_bytes())


def test_failed_nested_open_does_not_leak_ancestor_descriptors(skill):
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(20):
        with pytest.raises(source.SourceError):
            source.SkillSourceReader(lambda _: None).read(skill, skill.parent / "absent" / "reference.md")
    assert len(os.listdir("/proc/self/fd")) == before


def test_real_snapshot_crosses_authenticated_channel_without_text(skill, tmp_path):
    if os.getuid() == 0:
        pytest.skip("Non-root native peer profile")
    spec = importlib.util.spec_from_file_location("siq_source_channel", Path(__file__).parents[1] / "native_channel.py")
    channel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(channel)
    socket_dir = tmp_path / "socket"
    socket_dir.mkdir(mode=0o700)
    received = []
    with channel.ProcessPin(os.getpid(), os.getuid()) as peer, channel.HostChannel(socket_dir, peer) as host:
        client = channel.HermesChannel(host.path)

        def observe(event):
            assert client.exchange(event) == {"metadata_received": True}

        reader = source.SkillSourceReader(observe)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            for cached in (False, True):
                dispatched = pool.submit(host.serve_once, lambda event: received.append(event) or {"metadata_received": True})
                assert reader.read(skill, cache_hit=cached) == skill.read_text()
                dispatched.result(timeout=3)
    assert [event["cache_hit"] for event in received] == [False, True]
    assert str(skill) not in json.dumps(received) and "Synthetic task." not in json.dumps(received)


def test_managed_link_pair_needs_successful_install_observer(skill):
    owner = skill.with_name("private-owner-fixture")
    os.link(skill, owner)
    events = []

    def verified_pair(event):
        assert os.path.samefile(owner, skill)
        events.append(event)

    reader = source.SkillSourceReader(verified_pair, managed_link_pair=True)
    assert reader.read(skill) == skill.read_text()
    assert len(events) == 1
    os.link(skill, skill.with_name("unexpected-third-link"))
    assert_poisoned(reader, skill)
    assert len(events) == 1


def test_managed_link_pair_observer_failure_never_returns_text(skill):
    os.link(skill, skill.with_name("unapproved-link"))

    def rejected(_):
        raise RuntimeError("synthetic installation verification failure")

    reader = source.SkillSourceReader(rejected, managed_link_pair=True)
    assert_poisoned(reader, skill)
    assert_poisoned(reader, skill)


def test_managed_link_pair_change_during_observer_is_rejected(skill):
    os.link(skill, skill.with_name("owner-link"))

    def changed(_):
        os.link(skill, skill.with_name("racing-third-link"))

    reader = source.SkillSourceReader(changed, managed_link_pair=True)
    assert_poisoned(reader, skill)
