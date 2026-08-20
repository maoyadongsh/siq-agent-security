"""最小威胁检测流水线（P0-3）：纯静态分析器。

安全红线：
- 分析是纯静态的：绝不执行/导入被分析内容，Python 内容只过 ast.parse 树检查；
- 规则全部本地确定性实现（正则/字符串/AST），无外部依赖、无网络；
- 正则规则来自规则包（app.rulepack）：内置 app/data/threat_rules.v1.json，
  可选 SIQ_AS_THREAT_RULEPACK_PATH 外部签名更新包（验签失败/降级一律回退内置包）；
- Python AST 检查保留在代码中（非数据，见 _python_ast_checks）；
- 模型输出不参与处置（本模块不接任何模型）；
- 命中只记录行号、规则 id、片段 sha256 与截断脱敏摘要，原文整段不入库。
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass

from app.rulepack import load_rulepack

RULEPACK_VERSION, _RULES = load_rulepack()
ANALYZER_VERSION = f"siq.threat-static.v{RULEPACK_VERSION}"


def reload_rulepack() -> None:
    """重新加载规则包并更新模块级版本/规则（运维热更新、回滚或测试用）。"""
    global RULEPACK_VERSION, ANALYZER_VERSION, _RULES
    RULEPACK_VERSION, _RULES = load_rulepack()
    ANALYZER_VERSION = f"siq.threat-static.v{RULEPACK_VERSION}"

# 命中摘要截断长度：只存定位用片段，不存整行/整段原文
_EXCERPT_MAX = 40


@dataclass(frozen=True)
class RuleMatch:
    rule_id: str
    severity: str  # critical|high|medium|low
    confidence: float  # 0-1
    description: str
    impact: str
    remediation: str
    line: int | None  # 1-based；AST 命中为节点行号
    excerpt_sha256: str  # 命中片段哈希定位
    excerpt: str  # 截断脱敏摘要（≤40 字符）

    def to_record(self) -> dict:
        """入库/出站用的脱敏命中记录（不含 impact/remediation 描述性字段）。"""
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "confidence": self.confidence,
            "line": self.line,
            "excerpt_sha256": self.excerpt_sha256,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class AnalysisResult:
    sha256: str
    detected_type: str  # shell|python|javascript|powershell|binary|unknown
    matches: list[RuleMatch]


# ---------------------------------------------------------------------------
# 类型识别：魔数/内容嗅探 + 扩展名提示；保守，识别不了即 unknown
# ---------------------------------------------------------------------------

_BINARY_MAGIC = (
    b"\x7fELF",
    b"MZ",
    b"\xca\xfe\xba\xbe",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"PK\x03\x04",  # zip/jar 等打包产物按二进制处理（不展开）
)

_EXT_HINTS = {
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".exe": "binary",
    ".dll": "binary",
    ".so": "binary",
    ".bin": "binary",
    ".elf": "binary",
}

_CONTENT_TYPE_HINTS = {
    "text/x-shellscript": "shell",
    "application/x-sh": "shell",
    "text/x-python": "python",
    "application/javascript": "javascript",
    "text/javascript": "javascript",
}

_PY_MARKER = re.compile(r"^(?:import\s+\w+|from\s+\w+\s+import\s+|def\s+\w+\s*\()", re.MULTILINE)


def detect_type(
    content: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    """识别内容类型；保守策略：证据不足一律 unknown。"""
    head = content[:4096]
    for magic in _BINARY_MAGIC:
        if content.startswith(magic):
            return "binary"
    if head.startswith(b"#!"):
        shebang = head.split(b"\n", 1)[0].lower()
        if b"python" in shebang:
            return "python"
        if b"pwsh" in shebang or b"powershell" in shebang:
            return "powershell"
        if b"node" in shebang or b"deno" in shebang:
            return "javascript"
        if re.search(rb"(?:ba|z|da)?sh\b", shebang):
            return "shell"
    # NUL 字节是强二进制信号
    if b"\x00" in head:
        return "binary"
    if filename:
        dot = filename.rfind(".")
        if dot >= 0:
            hinted = _EXT_HINTS.get(filename[dot:].lower())
            if hinted:
                return hinted
    if content_type:
        hinted = _CONTENT_TYPE_HINTS.get(content_type.split(";")[0].strip().lower())
        if hinted:
            return hinted
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    if _PY_MARKER.search(text):
        return "python"
    return "unknown"


# ---------------------------------------------------------------------------
# Python AST 轻量检查（解析失败不报错，按文本规则结果为准）
# ---------------------------------------------------------------------------

def _attr_chain(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


_SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"gh[pousr]_[a-zA-Z0-9]{20,}"), "gh_***"),
    (re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{10,}"), "Bearer ***"),
    (re.compile(r"(?i)password\s*=\s*['\"][^'\"]+['\"]"), "password=***"),
    (re.compile(r"(?i)token\s*=\s*['\"][^'\"]+['\"]"), "token=***"),
    (re.compile(r"(?i)secret\s*=\s*['\"][^'\"]+['\"]"), "secret=***"),
]


def _redact_excerpt(text: str) -> str:
    sanitized = text
    for pattern, repl in _SECRET_PATTERNS:
        sanitized = pattern.sub(repl, sanitized)
    return sanitized


def _make_match(
    rule_id: str,
    severity: str,
    confidence: float,
    description: str,
    impact: str,
    remediation: str,
    line: int | None,
    excerpt_src: str,
) -> RuleMatch:
    redacted = _redact_excerpt(excerpt_src)
    excerpt = redacted[:_EXCERPT_MAX]
    return RuleMatch(
        rule_id=rule_id,
        severity=severity,
        confidence=confidence,
        description=description,
        impact=impact,
        remediation=remediation,
        line=line,
        excerpt_sha256=hashlib.sha256(excerpt_src.encode("utf-8", errors="replace")).hexdigest(),
        excerpt=excerpt,
    )


def _python_ast_checks(text: str, is_python_hint: bool = False) -> list[RuleMatch]:
    """os.system / subprocess+shell=True / ctypes 加载；语法错误显式告警（避免静默放行）。"""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as err:
        if is_python_hint or _PY_MARKER.search(text):
            lineno = getattr(err, "lineno", 1)
            return [
                _make_match(
                    "threat-py-syntax-parse-failed",
                    "medium",
                    0.75,
                    f"Python 语法解析失败 (行 {lineno}): 无法进行完整 AST 静态安全分析",
                    "语法错误可能被用于逃避 AST 规则检测，需人工审阅源码",
                    "修复脚本语法错误以启用完整 AST 分析",
                    lineno,
                    f"SyntaxError at line {lineno}",
                )
            ]
        return []
    found: dict[str, RuleMatch] = {}

    def add(match: RuleMatch) -> None:
        found.setdefault(match.rule_id, match)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _attr_chain(node.func)
        if name in ("os.system", "os.popen"):
            add(
                _make_match(
                    "threat-py-os-system",
                    "high",
                    0.95,
                    f"AST: 调用 {name}() 执行 shell 命令",
                    "直接 shell 命令执行，易注入且绕过参数化防护",
                    "改用 subprocess 参数数组形式并固定命令",
                    node.lineno,
                    f"{name}()",
                )
            )
        leaf = name.rsplit(".", 1)[-1]
        if "subprocess" in name and leaf in ("run", "call", "Popen", "check_output", "check_call"):
            shell_true = any(
                kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in node.keywords
            )
            if shell_true:
                add(
                    _make_match(
                        "threat-py-subprocess-shell",
                        "high",
                        0.9,
                        f"AST: subprocess.{leaf}(shell=True)",
                        "shell=True 拼接命令字符串存在命令注入面",
                        "移除 shell=True，使用参数数组",
                        node.lineno,
                        f"{name}(shell=True)",
                    )
                )
        if name in ("ctypes.CDLL", "ctypes.WinDLL", "ctypes.OleDLL") or name.endswith(".LoadLibrary"):
            add(
                _make_match(
                    "threat-py-ctypes-load",
                    "medium",
                    0.8,
                    f"AST: 动态加载本地库（{name}）",
                    "ctypes 加载任意本地库可执行非 Python 原生代码",
                    "审计加载的库路径；禁止加载不可信 so/dll",
                    node.lineno,
                    f"{name}(...)",
                )
            )
    return list(found.values())


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def analyze(
    content: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> AnalysisResult:
    """纯静态分析：sha256 + 类型识别 + 确定性规则/AST 命中。绝不执行内容。"""
    digest = hashlib.sha256(content).hexdigest()
    detected = detect_type(content, filename, content_type)
    text = content.decode("utf-8", errors="replace")

    matches: list[RuleMatch] = []
    lines = text.splitlines()
    for rule in _RULES:
        for lineno, line in enumerate(lines, 1):
            hit = next((pat.search(line) for pat in rule.patterns if pat.search(line)), None)
            if hit is not None:
                matches.append(
                    _make_match(
                        rule.rule_id,
                        rule.severity,
                        rule.confidence,
                        rule.description,
                        rule.impact,
                        rule.remediation,
                        lineno,
                        hit.group(0),
                    )
                )
                break  # 每条规则只记录首个命中（定位用）

    if detected == "python" or (filename and (filename.endswith(".py") or filename.endswith(".pyw"))):
        existing_ids = {m.rule_id for m in matches}
        for m in _python_ast_checks(text, is_python_hint=True):
            if m.rule_id not in existing_ids:
                matches.append(m)

    return AnalysisResult(sha256=digest, detected_type=detected, matches=matches)
