from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

from sms_relay_client import DEFAULT_URL, SmsRelayClient


ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("CODE_RELAY_CONFIG", ROOT / "sms_relay_config.json"))


def main() -> int:
    current = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    base_url = input(f"短信中转 HTTPS 地址 [{current.get('baseUrl', DEFAULT_URL)}]: ").strip()
    base_url = base_url or current.get("baseUrl", DEFAULT_URL)
    token = getpass.getpass("项目取码密钥（输入不显示）: ").strip()
    if not token:
        token = str(current.get("token", ""))
    if not token:
        try:
            token = SmsRelayClient.from_config().token
        except RuntimeError:
            pass
    if len(token) < 32:
        raise SystemExit("项目取码密钥不能为空，且长度至少为 32 个字符。")

    client = SmsRelayClient(base_url, token)
    client.check()
    client.recent(1)  # Auth check; do not print a returned code.
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(
        json.dumps({"baseUrl": base_url.rstrip("/"), "token": token, "pollIntervalSeconds": 2}, indent=2),
        encoding="utf-8",
    )
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass
    print(f"短信中转服务连接与项目密钥认证正常。配置已保存到：{CONFIG}")
    print("密钥不会在终端显示；请勿分享 sms_relay_config.json。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
