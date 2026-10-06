"""Guard Alembic's Mako dependency against Windows URI normalization regressions.

This exercises Windows path semantics on any CI host, not a native Windows run.
"""

import ntpath
from types import SimpleNamespace

import pytest
from mako import exceptions, template


def test_mako_rejects_drive_prefixed_parent_traversal(monkeypatch):
    monkeypatch.setattr(template, "os", SimpleNamespace(path=ntpath))
    with pytest.raises(exceptions.TemplateLookupException, match="outside"):
        template.Template(text="constant fixture", uri="C:/../../secret.txt")


def test_mako_keeps_normal_template_rendering(monkeypatch):
    monkeypatch.setattr(template, "os", SimpleNamespace(path=ntpath))
    value = template.Template(text="migration ${revision}", uri="safe/revision.txt")
    assert value.render(revision="test") == "migration test"
