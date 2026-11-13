"""mDNS 固定地址：让 PulsHealth 用同一个 ``*.local`` 地址跨 Wi-Fi 使用。

PulsHealth 保存的是完整 URL。电脑换 Wi-Fi 后 IP 会变，但 mDNS 名称不变；
这里把当前局域网 IP 作为 A 记录广播出去，手机继续用同一个地址即可。

注意：mDNS 依赖组播；部分公共/校园 Wi-Fi 会屏蔽组播或开启客户端隔离，
这种情况下仍需要改用局域网 IP、电脑热点或 Tailscale 等方案。
"""

from __future__ import annotations

import hashlib
import socket

try:  # 延迟到运行时才真正使用；导入失败时降级为仅 IP 模式
    from zeroconf import ServiceInfo, Zeroconf

    HAS_ZEROCONF = True
except Exception:  # noqa: BLE001
    ServiceInfo = None  # type: ignore[assignment]
    Zeroconf = None  # type: ignore[assignment]
    HAS_ZEROCONF = False

SERVICE_TYPE = "_http._tcp.local."


def stable_suffix(config) -> str:
    token = str(config.get("token") or "")
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:6]


def stable_hostname(config) -> str:
    return f"pulsebridge-{stable_suffix(config)}.local."


def stable_url(config, port: int) -> str:
    return f"http://{stable_hostname(config).rstrip('.')}:{int(port)}"


class MdnsAdvertiser:
    def __init__(self, hostname: str, port: int) -> None:
        self.hostname = hostname if hostname.endswith(".") else hostname + "."
        self.port = int(port)
        self.ip = ""
        self.error = ""
        self._zeroconf = None
        self._info = None

    @property
    def active(self) -> bool:
        return self._zeroconf is not None and self._info is not None

    def start(self, ip: str) -> bool:
        self.stop()
        self.ip = str(ip or "").strip()
        self.error = ""
        if not self.ip or self.ip.startswith("127."):
            self.error = "未找到局域网地址"
            return False
        if not HAS_ZEROCONF:
            self.error = "未安装 zeroconf（mDNS 不可用）"
            return False
        try:
            service_name = (
                self.hostname.rstrip(".").removesuffix(".local")
                + "._http._tcp.local."
            )
            info = ServiceInfo(
                SERVICE_TYPE,
                service_name,
                addresses=[socket.inet_aton(self.ip)],
                port=self.port,
                properties={"path": "/", "app": "PulseBridge"},
                server=self.hostname,
            )
            zeroconf = Zeroconf()
            zeroconf.register_service(info)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)[:240]
            try:
                if "zeroconf" in locals():
                    zeroconf.close()
            except Exception:  # noqa: BLE001
                pass
            self._zeroconf = None
            self._info = None
            return False
        self._zeroconf = zeroconf
        self._info = info
        return True

    def update(self, ip: str) -> bool:
        if ip and ip != self.ip:
            return self.start(ip)
        return self.active

    def stop(self) -> None:
        zeroconf, info = self._zeroconf, self._info
        self._zeroconf = None
        self._info = None
        if zeroconf is None:
            return
        try:
            if info is not None:
                zeroconf.unregister_service(info)
        except Exception:  # noqa: BLE001
            pass
        try:
            zeroconf.close()
        except Exception:  # noqa: BLE001
            pass
