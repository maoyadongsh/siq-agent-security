"""最小威胁检测流水线（P0-3）：纯静态分析器。

安全红线：
- 分析是纯静态的：绝不执行/导入被分析内容，Python 内容只过 ast.parse 树检查；
- 规则全部本地确定性实现（正则/字符串/AST），无外部依赖、无网络；
- 模型输出不参与处置（本模块不接任何模型）；
- 命中只记录行号、规则 id、片段 sha256 与截断脱敏摘要，原文整段不入库。
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass

ANALYZER_VERSION = "siq.threat-static.v1"

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


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    severity: str
    confidence: float
    description: str
    impact: str
    remediation: str
    patterns: tuple[re.Pattern[str], ...]


# ---------------------------------------------------------------------------
# 确定性规则集（本地正则/字符串，无网络无外部依赖）
# ---------------------------------------------------------------------------

_RULES: tuple[_Rule, ...] = (
    # ---- 下载执行 ----
    _Rule(
        rule_id="threat-download-exec-pipe",
        severity="critical",
        confidence=0.95,
        description="下载内容直接管道进 shell 执行（curl/wget | sh/bash）",
        impact="远程脚本未经审阅即执行，可完全控制主机",
        remediation="先下载落盘、人工审阅后再执行；禁止 curl|sh 模式",
        patterns=(re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:bash|sh|zsh|dash)\b"),),
    ),
    _Rule(
        rule_id="threat-download-exec-powershell",
        severity="critical",
        confidence=0.95,
        description="PowerShell 远程下载字符串并 IEX 执行",
        impact="远程脚本未经审阅即在 PowerShell 上下文执行",
        remediation="禁止 DownloadString|IEX；脚本落地签名验证后执行",
        patterns=(
            re.compile(
                r"\bIEX\b[^\n]*\bDownloadString\b|\bDownloadString\b[^\n]*\bIEX\b"
                r"|\b(?:iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^\n|]*\|\s*IEX\b",
                re.IGNORECASE,
            ),
        ),
    ),
    # ---- 凭据读取 ----
    _Rule(
        rule_id="threat-cred-ssh",
        severity="high",
        confidence=0.9,
        description="读取 SSH 私钥/授权密钥路径（~/.ssh/*）",
        impact="私钥泄露可导致横向移动与主机接管",
        remediation="禁止 Agent 脚本访问 ~/.ssh 私钥；按最小权限隔离",
        patterns=(
            re.compile(r"(?:~|\$HOME)/\.ssh/(?:id_rsa|id_ed25519|id_ecdsa|id_dsa|authorized_keys)"),
        ),
    ),
    _Rule(
        rule_id="threat-cred-dotenv",
        severity="high",
        confidence=0.85,
        description="读取 .env 类环境变量凭据文件",
        impact=".env 常含 API Key/数据库口令，读取即外泄风险",
        remediation="凭据走密钥管理引用，禁止脚本直读 .env",
        patterns=(
            re.compile(r"\b(?:cat|less|more|head|tail|cp|scp|source|tar|xxd|strings)\s+[^\n;&|]*\.env\b"),
        ),
    ),
    _Rule(
        rule_id="threat-cred-system-files",
        severity="high",
        confidence=0.9,
        description="访问系统账户文件（/etc/passwd、/etc/shadow）",
        impact="账户与口令哈希泄露，可离线爆破",
        remediation="Agent 无需读取系统账户文件；阻断并审计",
        patterns=(re.compile(r"/etc/(?:passwd|shadow)\b"),),
    ),
    _Rule(
        rule_id="threat-cred-cloud",
        severity="high",
        confidence=0.9,
        description="访问云凭据存储（AWS/GCP/Azure）",
        impact="云凭据泄露可导致整个账号被接管",
        remediation="使用实例元数据/托管身份，禁止直读凭据文件",
        patterns=(
            re.compile(
                r"\.aws/credentials|\.config/gcloud|application_default_credentials\.json|\.azure/"
            ),
        ),
    ),
    _Rule(
        rule_id="threat-cred-browser-store",
        severity="high",
        confidence=0.85,
        description="访问浏览器 cookie/口令存储",
        impact="会话 cookie 与保存的口令泄露，可劫持账户",
        remediation="阻断对浏览器 profile 存储的访问",
        patterns=(
            re.compile(
                r"(?:Chrome|Chromium|\.mozilla|Firefox|Safari|Microsoft/Edge)[^\n]{0,120}"
                r"(?:Cookies|Login Data|logins\.json|key4\.db|leveldb)"
            ),
        ),
    ),
    # ---- 持久化 ----
    _Rule(
        rule_id="threat-persist-crontab",
        severity="high",
        confidence=0.9,
        description="写入 crontab/cron 目录实现持久化",
        impact="重启后恶意任务持续执行",
        remediation="审计计划任务变更；禁止脚本自写 crontab",
        patterns=(
            re.compile(
                r"\|\s*crontab\b|\bcrontab\s+-(?![el]\b)|>\s*/etc/cron\.|/etc/cron\.(?:d|daily|hourly|weekly)/"
            ),
        ),
    ),
    _Rule(
        rule_id="threat-persist-systemd",
        severity="high",
        confidence=0.9,
        description="写入 systemd unit 或 systemctl enable 实现持久化",
        impact="恶意服务随系统启动并常驻",
        remediation="unit 文件变更需审批；禁止脚本自注册服务",
        patterns=(
            re.compile(
                r">\s*/etc/systemd/system/|\btee\s+[^\n]*systemd/system|\bsystemctl\s+(?:enable|reenable|link)\b"
            ),
        ),
    ),
    _Rule(
        rule_id="threat-persist-launchd",
        severity="high",
        confidence=0.9,
        description="写入 launchd LaunchAgents/Daemons 实现持久化（macOS）",
        impact="登录/启动时恶意载荷自动执行",
        remediation="审计 LaunchAgents 写入；禁止脚本自注册",
        patterns=(
            re.compile(r"Library/Launch(?:Agents|Daemons)|\blaunchctl\s+(?:load|bootstrap)\b"),
        ),
    ),
    _Rule(
        rule_id="threat-persist-shell-rc",
        severity="medium",
        confidence=0.8,
        description="向 shell rc 文件追加内容（.bashrc/.zshrc/.profile）",
        impact="下次登录 shell 自动执行注入内容",
        remediation="审计 rc 文件追加写入；区分正常 PATH 配置与注入",
        patterns=(
            # 文件名后必须是空白/行尾/引号：`.profile.d/custom` 这类目录前缀不误报
            re.compile(
                r">>?\s*(?:~|\$HOME)?/?\.(?:bashrc|zshrc|bash_profile|profile|zprofile|bash_login)(?:\s|$|[\"'])"
            ),
        ),
    ),
    _Rule(
        rule_id="threat-persist-run-key",
        severity="high",
        confidence=0.9,
        description="写 Windows Run 注册表键实现持久化",
        impact="用户登录时恶意程序自动启动",
        remediation="审计 Run 键写入；禁止脚本自注册自启",
        patterns=(re.compile(r"\\CurrentVersion\\Run\b", re.IGNORECASE),),
    ),
    # ---- 混淆/反射 ----
    _Rule(
        rule_id="threat-obf-base64-pipe-exec",
        severity="high",
        confidence=0.9,
        description="base64 解码后管道执行",
        impact="编码绕过文本审计后直接执行隐藏载荷",
        remediation="禁止 base64 -d | sh 模式；解码内容先审阅",
        patterns=(
            re.compile(
                r"\bbase64\s+(?:-d|-D|--decode)\b[^\n|]*\|\s*(?:sudo\s+)?(?:bash|sh|zsh|python\d*|perl)\b"
            ),
        ),
    ),
    _Rule(
        rule_id="threat-obf-eval-dynamic",
        severity="high",
        confidence=0.85,
        description="eval/exec 动态执行解码内容（atob/base64/marshal/zlib 等）",
        impact="真实载荷隐藏在编码层后，规避静态审阅",
        remediation="禁止对解码结果 eval/exec；展开后重新审计",
        patterns=(
            re.compile(
                r"\b(?:eval|exec|Function)\s*\(\s*(?:atob|base64|unquote|unescape|bytes\.fromhex|"
                r"marshal|zlib|__import__|String\.fromCharCode)"
            ),
        ),
    ),
    _Rule(
        rule_id="threat-obf-base64-blob",
        severity="medium",
        confidence=0.6,
        description="超长 base64 块（疑似内嵌编码载荷）",
        impact="可能隐藏二进制载荷或外泄数据",
        remediation="展开审查超长编码块来源与用途",
        patterns=(re.compile(r"[A-Za-z0-9+/]{240,}={0,2}"),),
    ),
    _Rule(
        rule_id="threat-obf-py-marshal",
        severity="high",
        confidence=0.85,
        description="Python marshal/pickle/zlib 反序列化后动态执行",
        impact="编译后字节码规避源码审计",
        remediation="禁止 marshal/pickle 加载不可信数据并 exec",
        patterns=(
            re.compile(r"\b(?:marshal|pickle)\.loads\b|\bexec\s*\(\s*zlib\.decompress"),
        ),
    ),
    # ---- 外联/外传 ----
    _Rule(
        rule_id="threat-net-reverse-shell",
        severity="critical",
        confidence=0.95,
        description="反弹 shell（bash /dev/tcp、nc -e 等）",
        impact="攻击者获得交互式远程控制通道",
        remediation="阻断 /dev/tcp 与 nc -e；出站连接白名单",
        patterns=(
            re.compile(r"/dev/tcp/|\bnc(?:at)?\s+[^\n;&]*\s-e\s|\b(?:nc|ncat)\b[^\n]*\|\s*(?:/bin/)?(?:ba)?sh\b"),
        ),
    ),
    _Rule(
        rule_id="threat-net-hardcoded-c2",
        severity="high",
        confidence=0.8,
        description="硬编码 IP:端口 反连（疑似 C2）",
        impact="绕过域名审计直连控制端",
        remediation="出站连接走白名单与域名审计；阻断裸 IP 反连",
        patterns=(
            re.compile(
                r"\(\s*['\"]\d{1,3}(?:\.\d{1,3}){3}['\"]\s*,\s*\d{2,5}\s*\)"
                r"|\bnc\s+\d{1,3}(?:\.\d{1,3}){3}\s+\d{2,5}\b"
            ),
        ),
    ),
    _Rule(
        rule_id="threat-net-webhook-exfil",
        severity="medium",
        confidence=0.7,
        description="向 webhook/匿名回调地址发送数据（疑似外传）",
        impact="凭据/数据经第三方回调通道外泄",
        remediation="审计向 webhook.site/Discord/Slack hooks 的数据发送",
        patterns=(
            re.compile(
                r"(?:\bcurl\b|\brequests\.(?:post|put)\b|\bfetch\s*\(|\bInvoke-RestMethod\b)[^\n]{0,200}"
                r"(?:webhook\.site|discord(?:app)?\.com/api/webhooks|hooks\.slack\.com/services|\.ngrok\.io)",
                re.IGNORECASE,
            ),
        ),
    ),
    # ---- 提示注入载荷 ----
    _Rule(
        rule_id="threat-prompt-injection",
        severity="high",
        confidence=0.9,
        description="提示注入载荷（覆盖指令/控制 token/越狱短语）",
        impact="诱导 Agent 忽略既定指令，执行注入者意图",
        remediation="含提示注入的内容不得进入模型上下文；隔离并审计来源",
        patterns=(
            re.compile(
                r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+"
                r"(?:instructions|prompts|messages|directions)",
                re.IGNORECASE,
            ),
            re.compile(r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|<<SYS>>|\[INST\]"),
            re.compile(
                r"\bDAN\b\s*(?:mode|prompt|jailbreak)|do\s+anything\s+now|jailbreak\s+(?:prompt|mode|attack)",
                re.IGNORECASE,
            ),
        ),
    ),
)


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
    excerpt = excerpt_src[:_EXCERPT_MAX]
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


def _python_ast_checks(text: str) -> list[RuleMatch]:
    """os.system / subprocess+shell=True / ctypes 加载；语法错误静默跳过。"""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
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

    if detected == "python":
        existing_ids = {m.rule_id for m in matches}
        for m in _python_ast_checks(text):
            if m.rule_id not in existing_ids:
                matches.append(m)

    return AnalysisResult(sha256=digest, detected_type=detected, matches=matches)
