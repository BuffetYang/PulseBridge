from __future__ import annotations

from pulsebridge.firewall import firewall_rule_command


def test_firewall_rule_command() -> None:
    command = firewall_rule_command(8765)
    assert "localport=8765" in command
    assert "dir=in" in command
    assert "action=allow" in command
    assert "remoteip=localsubnet" in command
    assert "PulseBridge Health Receiver" in command
    assert "protocol=UDP" in command
    assert "localport=5353" in command
    assert "PulseBridge mDNS" in command
