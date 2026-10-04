"""Client for the private HTTPS SMS code relay."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_URL = "https://www.hec-hsx.top"
DEFAULT_CONFIG = ROOT / "sms_relay_config.json"
LOCAL_CREDENTIALS = Path.home() / ".local/share/sms-code-relay/credentials.json"


def _load_settings() -> dict:
    settings = {}
    path = Path(os.environ.get("CODE_RELAY_CONFIG", DEFAULT_CONFIG))
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise RuntimeError("sms_relay_config.json 顶层必须是 JSON 对象")

    base_url = os.environ.get("CODE_RELAY_URL") or settings.get("baseUrl") or DEFAULT_URL
    token = os.environ.get("CODE_RELAY_TOKEN") or settings.get("token")
    if not token and settings.get("credentialsFile"):
        creds_path = Path(settings["credentialsFile"]).expanduser()
        token = _client_token(creds_path, settings.get("clientName", "default"))
    if not token and LOCAL_CREDENTIALS.exists():
        token = _client_token(LOCAL_CREDENTIALS, "default")
    if not token:
        raise RuntimeError(
            "未配置项目取码密钥。请设置 CODE_RELAY_TOKEN，或复制 "
            "sms_relay_config.example.json 为 sms_relay_config.json 并填写 token。"
        )
    base_url = str(base_url).rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("短信中转服务地址必须使用 HTTPS")
    return {"base_url": base_url, "token": str(token), "poll_interval": float(settings.get("pollIntervalSeconds", 2))}


def _client_token(path: Path, client_name: str) -> str | None:
    if not path.exists():
        return None
    credentials = json.loads(path.read_text(encoding="utf-8"))
    token = credentials.get("clients", {}).get(client_name)
    if not token:
        raise RuntimeError(f"凭据文件中没有名为 {client_name!r} 的项目取码密钥")
    return str(token)


class SmsRelayClient:
    def __init__(self, base_url: str, token: str, poll_interval: float = 2):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.poll_interval = min(max(poll_interval, 0.5), 10)

    @classmethod
    def from_config(cls) -> "SmsRelayClient":
        settings = _load_settings()
        return cls(settings["base_url"], settings["token"], settings["poll_interval"])

    def _get(self, path: str, timeout: int = 10) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Authorization": f"Bearer {self.token}", "Cache-Control": "no-store"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError("短信中转服务拒绝认证，请检查项目取码密钥") from exc
            if exc.code == 403:
                raise RuntimeError("项目密钥没有读取该短信发送方的权限") from exc
            raise RuntimeError(f"短信中转服务返回 HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接短信中转服务：{exc.reason}") from exc

    def check(self) -> None:
        request = urllib.request.Request(self.base_url + "/healthz", headers={"Cache-Control": "no-store"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError(f"短信中转服务健康检查失败：HTTP {response.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接短信中转服务：{exc.reason}") from exc

    def latest_cursor(self) -> int:
        return max((int(item.get("id", 0)) for item in self.recent(50)), default=0)

    def recent(self, limit: int = 1) -> list[dict]:
        if not 1 <= limit <= 50:
            raise ValueError("limit 必须在 1 到 50 之间")
        data = self._get(f"/v1/codes/recent?limit={limit}")
        return data.get("items", [])

    def wait_for_code(self, after_id: int, timeout: int, sender_contains: str | None = None) -> str:
        deadline = time.monotonic() + timeout
        sender_contains = (sender_contains or "").strip().casefold()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{timeout} 秒内未收到新的短信验证码")
            data = {"items": self.recent(50)}
            candidates = sorted(
                (item for item in data.get("items", []) if int(item.get("id", 0)) > after_id),
                key=lambda item: int(item.get("id", 0)),
            )
            for item in candidates:
                sender = str(item.get("sender", ""))
                code = str(item.get("code", ""))
                if sender_contains and sender_contains not in sender.casefold():
                    continue
                if code.isdigit() and 4 <= len(code) <= 8:
                    return code
            time.sleep(min(self.poll_interval, remaining))
