# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from typing import Any, Dict

import webview

from settings import APP_NAME, APP_VERSION, MAX_MASSIQUES, load_settings, save_settings, load_tags, save_tags
from devices import MassiqueManager, list_com_ports

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class Api:
    """
    Méthodes appelables depuis JS:
    await window.pywebview.api.method(...)
    """
    def __init__(self, mgr: MassiqueManager):
        self.mgr = mgr
        self.settings = load_settings()

    # --- app / ui ---
    def get_app_info(self) -> Dict[str, Any]:
        return {"name": APP_NAME, "version": APP_VERSION, "max": MAX_MASSIQUES, "settings": self.settings}

    def set_theme(self, theme: str) -> bool:
        self.settings["theme"] = theme
        save_settings(self.settings)
        return True

    # --- serial ---
    def list_ports(self) -> list[str]:
        return list_com_ports()

    def connect(self, port: str) -> Dict[str, Any]:
        self.mgr.connect(port)
        return self.mgr.snapshot()

    def disconnect(self) -> Dict[str, Any]:
        self.mgr.disconnect()
        return self.mgr.snapshot()

    # --- devices ---
    def snapshot(self) -> Dict[str, Any]:
        return self.mgr.snapshot()

    def set_tag(self, idx: int, tag: str) -> bool:
        tags = load_tags()
        tag8 = str(tag)[:8].ljust(8, "_")
        tags[idx] = tag8
        save_tags(tags)
        self.mgr.set_tag(idx, tag8)
        return True

    def toggle_device(self, idx: int, on: bool) -> Dict[str, Any]:
        if on:
            self.mgr.activate(idx)
        else:
            self.mgr.deactivate(idx)
        return self.mgr.snapshot()

    def set_consigne(self, idx: int, consigne: float) -> Dict[str, Any]:
        self.mgr.send_consigne(idx, consigne)
        return self.mgr.snapshot()

    def set_vanne(self, idx: int, action: str) -> Dict[str, Any]:
        self.mgr.set_vanne(idx, action)
        return self.mgr.snapshot()

    def reset_total(self, idx: int) -> Dict[str, Any]:
        self.mgr.reset_totalization(idx)
        return self.mgr.snapshot()

    def set_ramp(self, idx: int, active: bool, time_s: float) -> Dict[str, Any]:
        self.mgr.apply_ramp_settings(idx, active, time_s)
        return self.mgr.snapshot()

    def select_gas(self, idx: int, gas_name: str) -> Dict[str, Any]:
        self.mgr.select_gas(idx, gas_name)
        return self.mgr.snapshot()


def main():
    tags = load_tags()
    mgr = MassiqueManager(tags=tags, max_devices=MAX_MASSIQUES)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.abspath(os.path.join(base_dir, "..", "web"))
    index_html = os.path.join(web_dir, "index.html")

    api = Api(mgr)

    window = webview.create_window(
        title=f"{APP_NAME} – {APP_VERSION}",
        url=index_html,
        js_api=api,
        width=1200,
        height=820,
    )

    webview.start(debug=False)  # debug=True => console dev + reload plus simple


if __name__ == "__main__":
    main()
