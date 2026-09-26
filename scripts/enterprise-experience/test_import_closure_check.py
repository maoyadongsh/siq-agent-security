"""`scripts/enterprise-experience/import-closure-check.py` 的合成回归守卫。

**不碰真实仓库、不碰共享工作树、不连任何数据库或服务。** 每个用例在 `tmp_path` 里现造一个
**一次性合成 git 仓**：一个迷你 `apps/control-api`（`app/main.py` + 几个模块），按用例需要
决定「哪些文件已提交、哪些只在工作树里」。被测工具对这个合成仓做只读核验。

要钉住的性质：

1. **ref 自足**时结论必须是 `import_closure_closed_at_ref`、零补件、退出码 0；
2. **闭包开着**时必须点名**缺哪个工作树文件**（相对仓库根的路径）、标明它在工作树里的状态
   （已跟踪被改 / 未跟踪），并给已跟踪件的增删行数；退出码非 0（「闭包开着」不是绿）；
3. **`from 包 import 名` 的两义性**（R09.17 的真实形状）：当缺的是**包下未提交的子模块**时，
   必须补 `包/名.py`，**不能**把包的 `__init__.py` 反复重拷——这是工具首版真的踩过的坑
   （空转到轮次耗尽、补件数为 0），此处作为回归守卫钉住；
4. **无进展即停**：同一份工作树文件再拷一次不可能改变结果，必须立刻以 `no_progress` 有界结束，
   不许空转；
5. 工作树里也定位不到 → `import_closure_unresolvable`（不许假装"补工作树文件能解决"）；
6. **边界**：证据目录独占创建（已存在即拒绝且不写一个字）；留痕不含绝对路径；
   `writes_to_repo=False`、`production_eligible=False`、`enforcement_verified=False`；
   临时目录在结束时删除；
7. **路径泄漏守卫**：`app` 解析到临时树之外时结论作废（真实撞到过：cwd 下另有可导入的 `app`）。
   这一条只测守卫函数本身——从外面无法注入泄漏，工具自己构造子进程环境。

「合成仓上全绿/全红」只说明这条核验链路在替身上按预期工作，**不构成任何真实仓库结论**。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "enterprise-experience" / "import-closure-check.py"
SUBTREE = "apps/control-api"
GIT_ID = ("-c", "user.email=bench@example.invalid", "-c", "user.name=bench")


def _load_module():
    spec = importlib.util.spec_from_file_location("import_closure_check_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *GIT_ID, *args],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, (args, proc.stderr)
    return proc.stdout


def _write(repo: Path, rel: str, text: str) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _bench(tmp_path: Path, *, models: str, main: str, routers_init: str = "") -> Path:
    """造一个合成仓：写入给定内容并**全部提交**，返回仓库根（工作树 = 提交内容）。

    想造「只在工作树里存在」的文件，由调用方在返回后自行写入（那就是未跟踪状态）。
    """
    repo = tmp_path / "bench-repo"
    (repo / SUBTREE).mkdir(parents=True)
    _write(repo, f"{SUBTREE}/app/__init__.py", "")
    _write(repo, f"{SUBTREE}/app/models.py", models)
    _write(repo, f"{SUBTREE}/app/main.py", main)
    _write(repo, f"{SUBTREE}/app/routers/__init__.py", routers_init)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bench")
    return repo


def _run(repo: Path, out: Path, *extra: str, read_record: bool = True):
    proc = subprocess.run([sys.executable, str(TOOL), "--repo", str(repo), "--out", str(out), *extra],
                          capture_output=True, text=True, check=False)
    record = None
    if read_record and (out / "report.json").is_file():
        record = json.loads((out / "report.json").read_text(encoding="utf-8"))
    return proc, record


def test_clean_ref_is_self_sufficient(tmp_path):
    repo = _bench(tmp_path, models="class Thing: pass\n",
                  main="from app.models import Thing\n")
    proc, record = _run(repo, tmp_path / "out")
    assert proc.returncode == 0, proc.stderr
    assert record["conclusion"] == "import_closure_closed_at_ref"
    assert record["grafted_paths"] == [] and record["grafted_count"] == 0
    assert record["rounds"] == [{"round": 1, "result": "import_ok"}]
    assert record["temp_dir_removed"] is True


def test_open_closure_names_the_tracked_file_and_its_diff_size(tmp_path):
    repo = _bench(tmp_path, models="class Base: pass\n",
                  main="from app.models import Thing\n")
    _write(repo, f"{SUBTREE}/app/models.py", "class Base: pass\n\n\nclass Thing: pass\n")
    proc, record = _run(repo, tmp_path / "out")
    assert proc.returncode == 1, proc.stdout
    assert record["conclusion"] == "import_closure_open"
    assert record["grafted_count"] == 1
    entry = record["grafted_paths"][0]
    assert entry["path"] == f"{SUBTREE}/app/models.py"
    assert entry["kind"] == "tracked_modified_in_worktree"
    # 增删行数直接取自 `git diff --numstat`（合成夹具里是 3 增 0 删）
    assert entry["insertions"] == "3" and entry["deletions"] == "0"
    assert record["rounds"][-1]["result"] == "import_ok"


def test_missing_package_submodule_grafts_the_submodule_not_the_package(tmp_path):
    """R09.17 的真实形状：`from app.routers import foo` 而 `app/routers/foo.py` 未提交。"""
    repo = _bench(tmp_path, models="", routers_init="",
                  main="from app.routers import foo\n\nassert foo.NAME\n")
    _write(repo, f"{SUBTREE}/app/routers/foo.py", "NAME = 'bar'\n")  # 提交之后才写 ⇒ 未跟踪
    proc, record = _run(repo, tmp_path / "out")
    assert proc.returncode == 1
    assert record["conclusion"] == "import_closure_open"
    paths = [item["path"] for item in record["grafted_paths"]]
    assert paths == [f"{SUBTREE}/app/routers/foo.py"], paths
    assert record["grafted_paths"][0]["kind"] == "untracked_in_worktree"
    # 回归守卫：包 __init__.py 不该被重拷（首版正是在这里空转到轮次耗尽）
    assert f"{SUBTREE}/app/routers/__init__.py" not in paths


def test_no_progress_stops_instead_of_spinning(tmp_path):
    """工作树里那份文件也缺符号 → 补一次后原地不动，必须立刻停，不许空转。"""
    repo = _bench(tmp_path, models="class Base: pass\n",
                  main="from app.models import Thing\n")
    proc, record = _run(repo, tmp_path / "out", "--max-rounds", "25")
    assert proc.returncode == 1
    assert record["reason"] == "no_progress"
    assert record["failed"] is True
    # `rounds_used` = 第几轮判定停手：第 1 轮补入，第 2 轮发现又是同一份文件 ⇒ 停在第 2 轮
    assert record["rounds_used"] == 2
    assert record["repeated_path"] == f"{SUBTREE}/app/models.py"
    assert record["grafted_count"] == 1


def test_unresolvable_module_is_reported_as_such(tmp_path):
    repo = _bench(tmp_path, models="", main="import app.nonexistent_module\n")
    proc, record = _run(repo, tmp_path / "out")
    assert proc.returncode == 1
    assert record["conclusion"] == "import_closure_unresolvable"
    assert record["grafted_count"] == 0
    assert record["rounds"][-1]["result"] == "unresolvable"
    assert record["rounds"][-1]["candidates"] == ["app.nonexistent_module"]


def test_output_dir_is_exclusive_and_report_has_no_absolute_paths(tmp_path):
    repo = _bench(tmp_path, models="class Thing: pass\n",
                  main="from app.models import Thing\n")
    out = tmp_path / "out"
    out.mkdir()
    sentinel = out / "report.json"
    sentinel.write_text("original\n", encoding="utf-8")
    proc, _ = _run(repo, out, read_record=False)
    assert proc.returncode == 2, proc.stdout
    assert sentinel.read_text(encoding="utf-8") == "original\n"

    fresh = tmp_path / "out2"
    _, record = _run(repo, fresh)
    text = (fresh / "report.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text and str(repo) not in text
    assert record["writes_to_repo"] is False
    assert record["production_eligible"] is False
    assert record["enforcement_verified"] is False
    assert record["temp_dir_removed"] is True


def test_app_outside_the_extraction_is_a_bounded_failure(tmp_path):
    """路径泄漏守卫：解析到的 app 不在临时树内 → 结论作废（真实撞到过的坑）。"""
    module = _load_module()
    root = tmp_path / "extraction"
    (root / "app").mkdir(parents=True)
    inside = root / "app" / "__init__.py"
    inside.write_text("", encoding="utf-8")
    outside = tmp_path / "elsewhere" / "app" / "__init__.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("", encoding="utf-8")
    assert module.assert_app_under_root(str(inside), root) is True
    assert module.assert_app_under_root(str(outside), root) is False
    assert module.assert_app_under_root(None, root) is False


def test_records_are_gone_after_the_run(tmp_path):
    before = set(Path("/tmp").glob("siq-import-closure-*"))
    repo = _bench(tmp_path, models="class Base: pass\n",
                  main="from app.models import Thing\n")
    _run(repo, tmp_path / "out")
    assert set(Path("/tmp").glob("siq-import-closure-*")) == before


@pytest.mark.parametrize("ref", ["HEAD", "HEAD~0"])
def test_same_ref_resolves(tmp_path, ref):
    repo = _bench(tmp_path, models="class Thing: pass\n",
                  main="from app.models import Thing\n")
    _, record = _run(repo, tmp_path / "out", "--ref", ref)
    assert record["conclusion"] == "import_closure_closed_at_ref"
    assert len(record["ref_sha"]) == 40
