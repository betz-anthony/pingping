#!/usr/bin/env python3
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Tree, Static
from textual.containers import Horizontal
from textual.binding import Binding
import asyncio
import subprocess
import re
import socket
import platform
from pathlib import Path
import configparser

# =========================
# CONFIG
# =========================
def build_tree(config_path: Path):
    config = configparser.ConfigParser()
    config.read(config_path)
    root = {"hosts": [], "children": {}}

    for section in config.sections():
        parts = section.split(".")
        current = root
        for part in parts:
            current = current["children"].setdefault(part, {"hosts": [], "children": {}})
        raw = config.get(section, "hosts", fallback="")
        current["hosts"] = [line.strip() for line in raw.splitlines() if line.strip()]

    return root

# =========================
# NETWORK
# =========================
dns_cache = {}

def resolve(host: str):
    if host in dns_cache:
        return dns_cache[host]
    try:
        ip = socket.gethostbyname(host)
        dns_cache[host] = ip
        return ip
    except Exception:
        dns_cache[host] = None
        return None
def ping(host: str):
    ip = resolve(host)
    if not ip:
        return None, "DNS_FAIL"

    try:
        if platform.system() == "Darwin":
            cmd = ["ping", "-c", "1", "-t", "2", ip]
        else:
            cmd = ["ping", "-c", "1", "-W", "2", ip]

        out = subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL, timeout=3, text=True
        )
        m = re.search(r"time[=<]([\d.]+)", out)
        if m:
            return float(m.group(1)), "OK"
        return None, "UNKNOWN"
    except subprocess.CalledProcessError:
        return None, "TIMEOUT"
    except Exception:
        return None, "ERROR"

# =========================
# UI HELPERS
# =========================
def heat_bar(rtt):
    if rtt is None:
        return "██████████"
    blocks = min(10, int(rtt / 20))
    return "█" * blocks + "░" * (10 - blocks)

def colorize(host: str, rtt, status: str):
    if status != "OK":
        return f"[bold red]{host} {status}[/]"
    if rtt < 50:
        color = "green"
    elif rtt < 100:
        color = "cyan"
    elif rtt < 150:
        color = "yellow"
    elif rtt < 250:
        color = "magenta"
    else:
        color = "red"
    return f"[{color}]{host} {rtt:.1f} ms[/]"

# =========================
# APP
# =========================
class PingApp(App):
    # Add 'q' binding to quit (Shown in footer)
    BINDINGS = [
        Binding("q","quit","Quit", show=True),
        Binding("r","force_refresh", "Refresh", show=True),
    ]
    CSS = """
    Screen {
        layout: vertical;
    }
    #main {
        layout: horizontal;
        height: 1fr;
    }
    Tree {
        width: 40%;
        border: solid green;
        padding: 1;
    }
    #details {
        width: 60%;
        border: solid cyan;
        padding: 1;
    }
    """

    def __init__(self, tree_data):
        super().__init__()
        self.tree_data = tree_data
        self.host_nodes = {}      # host -> TreeNode
        self.results = {}         # host -> (rtt, status)

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main"):
            self.ping_tree = Tree("PingPing")
            yield self.ping_tree

            self.details_panel = Static("Select a host from the tree...", id="details")
            yield self.details_panel

        yield Footer()

    def on_mount(self):
        self.ping_tree.root.expand()
        self.build_ui_tree(self.ping_tree.root, self.tree_data)
        self.set_interval(1.0, self.refresh_pings)
    def build_ui_tree(self, parent, node):
        for host in node.get("hosts", []):
            n = parent.add_leaf(host)
            self.host_nodes[host] = n

        for name, child in node.get("children", {}).items():
            branch = parent.add(name)
            self.build_ui_tree(branch, child)

    async def refresh_pings(self):
        tasks = []
        for host in list(self.host_nodes.keys()):
            tasks.append(self._ping_one(host))

        if tasks:
            await asyncio.gather(*tasks)

    async def _ping_one(self, host: str):
        rtt, status = await asyncio.to_thread(ping, host)
        self.results[host] = (rtt, status)

        if host in self.host_nodes:
            label = f"{colorize(host, rtt, status)} {heat_bar(rtt)}"
            self.host_nodes[host].set_label(label)

    def build_ui_tree(self, parent, node):
        for host in node.get("hosts", []):
            n = parent.add_leaf(host)
            self.host_nodes[host] = n

        for name, child in node.get("children", {}).items():
            branch = parent.add(name)
            self.build_ui_tree(branch, child)

    async def refresh_pings(self):
        """Auto-refresh (called by interval)"""
        await self._do_refresh()

    async def action_force_refresh(self):
        """Force refresh when user presses 'r'"""
        await self._do_refresh()
        

    async def _do_refresh(self):
        tasks = []
        for host in list(self.host_nodes.keys()):
            tasks.append(self._ping_one(host))

        if tasks:
            await asyncio.gather(*tasks)

    async def _ping_one(self, host: str):
        rtt, status = await asyncio.to_thread(ping, host)
        self.results[host] = (rtt, status)

        if host in self.host_nodes:
            label = f"{colorize(host, rtt, status)} {heat_bar(rtt)}"
            self.host_nodes[host].set_label(label)

    def on_tree_node_highlighted(self, event):
        node = event.node
        # Extract clean hostname
        label_plain = str(node.label).split(" ", 1)[0]

        if label_plain in self.results:
            rtt, status = self.results[label_plain]
            text = f"""[bold]Host:[/] {label_plain}
[bold]Status:[/] {status}
[bold]RTT:[/] {rtt if rtt is not None else 'N/A'} ms
[bold]Bar:[/] {heat_bar(rtt)}
"""
            self.details_panel.update(text)
        else:
            self.details_panel.update(f"Selected: {node.label}\n\nNo ping data yet.")
# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    config_path = Path("pingping.conf")

    if config_path.exists():
        tree_data = build_tree(config_path)
    else:
        tree_data = {
            "hosts": ["8.8.8.8", "1.1.1.1"],
            "children": {}
        }

    PingApp(tree_data).run()
