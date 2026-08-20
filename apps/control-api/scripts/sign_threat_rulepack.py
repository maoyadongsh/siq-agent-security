#!/usr/bin/env python3
"""威胁规则包签名工具（P2 运维流程）。

更新流程：
1. 编写新版本规则包 JSON（version 必须 >= 当前内置版本，否则加载时被拒绝回退，
   防回滚降级；格式见 app/data/threat_rules.v1.json）；
2. 签名：在与 control-api 相同签名密钥的环境下运行
   `uv run python scripts/sign_threat_rulepack.py path/to/threat_rules.v2.json`，
   在旁边生成 `threat_rules.v2.json.sig`（base64 Ed25519 签名；签名输入 =
   规则包 JSON 的规范序列化：sort_keys + 紧凑分隔符，与 app.signing 一致）；
3. 分发：将规则包 JSON 与 .sig 一起分发到目标主机（离线缓存 = 本地文件路径，
   无网络依赖）；
4. 生效：设置环境变量 SIQ_AS_THREAT_RULEPACK_PATH 指向该 JSON 后重启/重载；
   验签失败、缺 .sig、JSON 畸形、字段缺漏、正则不可编译、版本低于内置包，
   一律拒绝并回退内置包（fail-closed），拒绝原因见日志（不含规则内容）；
5. 回滚：将 SIQ_AS_THREAT_RULEPACK_PATH 指回旧版本文件，或移除该变量回到内置包。

密钥：复用 app.signing 的控制面密钥加载——生产由 SIQ_AS_TASK_SIGNING_KEY_SEED
（base64，32 字节，来自 Secret Manager）注入；dev 用 SIQ_AS_SIGNING_KEY_FILE
指定的开发密钥文件。secret 只经环境变量注入，不落库、不进日志。
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from app.rulepack import _parse_rulepack  # 先校验格式，拒绝签发非法包
from app.signing import _canonical_bytes, get_signing_key


def main() -> int:
    parser = argparse.ArgumentParser(description="签名威胁规则包，生成同名 .sig 文件")
    parser.add_argument("rulepack", help="规则包 JSON 路径")
    args = parser.parse_args()

    path = Path(args.rulepack)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version, rules = _parse_rulepack(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"规则包非法，拒绝签名: {exc}", file=sys.stderr)
        return 1

    signature = get_signing_key().sign(_canonical_bytes(data))
    sig_path = path.with_name(path.name + ".sig")
    sig_path.write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii")
    print(f"已签名: {path} (version={version}, rules={len(rules)}) -> {sig_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
