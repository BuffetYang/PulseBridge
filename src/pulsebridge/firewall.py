"""Windows 防火墙辅助：为接收端口添加入站规则。

Windows 会把家庭 Wi-Fi 识别为「公用网络」，公用网络默认拦截所有入站连接。
这一步需要管理员权限，因此通过 UAC 提权执行一条 netsh 命令。
"""

from __future__ import annotations

import sys

RULE_NAME = "PulseBridge Health Receiver"


def firewall_rule_command(port: int) -> str:
    # 同一个提权窗口内先删除旧规则再添加，重复执行是幂等的
    return (
        f'netsh advfirewall firewall delete rule name="{RULE_NAME}" >nul 2>&1 & '
        f'netsh advfirewall firewall add rule name="{RULE_NAME}" dir=in action=allow '
        f"protocol=TCP localport={int(port)} profile=any remoteip=localsubnet"
    )


def add_firewall_rule_elevated(port: int) -> tuple[bool, str]:
    """弹 UAC 并添加规则。返回 ``(是否已发起, 错误信息)``。"""
    if sys.platform != "win32":
        return False, "仅 Windows 需要配置防火墙。"
    try:
        import ctypes

        # SW_SHOWNORMAL = 1；ShellExecuteW 返回值 > 32 表示成功
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "cmd.exe", f"/c {firewall_rule_command(port)}", None, 1
        )
        if result > 32:
            return True, ""
        if result == 5:
            return False, "已取消管理员授权（UAC）。"
        return False, f"无法启动管理员权限窗口（错误码 {result}）。"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
