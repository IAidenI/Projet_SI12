# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import serial
import serial.tools.list_ports
from sprotocol import device  # ton driver Brooks

log = logging.getLogger(__name__)


def list_com_ports() -> list[str]:
    return [p.device for p in serial.tools.list_ports.comports()]


def open_serial_port(port: str) -> serial.Serial:
    # reprend tes réglages (19200, ODD, 8N1 stopbits 1)
    try:
        return serial.Serial(
            port,
            baudrate=19200,
            timeout=1,
            parity=serial.PARITY_ODD,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
        )
    except serial.SerialException as e:
        raise RuntimeError(f"Impossible d'ouvrir le port série {port}: {e}") from e


def pack_tag_name(tag: str) -> bytes:
    # repris de ton code
    tag = tag[:8].ljust(8, "_")
    packed = bytearray()
    for i in range(0, 8, 4):
        c = [ord(ch) & 0x3F for ch in tag[i : i + 4]]
        packed.extend([
            (c[0] << 2) | (c[1] >> 4),
            ((c[1] & 0x0F) << 4) | (c[2] >> 2),
            ((c[2] & 0x03) << 6) | c[3],
        ])
    return bytes(packed)


@dataclass
class DeviceState:
    index: int
    tag: str

    active: bool = False
    selected_gas: Optional[int] = None
    available_gases: List[str] = field(default_factory=list)
    gas_map: Dict[str, int] = field(default_factory=dict)

    consigne: float = 0.0
    full_scale_value: float = 0.0

    mesure: Tuple[Any, str] = (0, "N/A")
    temperature: Tuple[Any, str] = (0, "N/A")
    full_scale: Tuple[Any, str] = (0, "N/A")
    totalization_value: Tuple[Any, str] = (0, "N/A")
    valve_command: str = "N/A"

    ramp_active: bool = False
    ramp_time_s: float = 1.0

    measurements: List[Tuple[float, datetime.datetime]] = field(default_factory=list)
    consigne_points: List[Tuple[float, datetime.datetime]] = field(default_factory=list)


class MassiqueManager:
    def __init__(self, tags: list[str], max_devices: int = 12):
        self.serial_lock = threading.Lock()
        self.serial_port: Optional[serial.Serial] = None
        self.max_devices = max_devices

        self.devices: List[DeviceState] = [
            DeviceState(index=i, tag=tags[i] if i < len(tags) else f"MFC{i+1:05d}"[:8].ljust(8, "_"))
            for i in range(max_devices)
        ]

        self._mfc_objs: List[Optional[Any]] = [None] * max_devices

        self._poll_stop = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None

    # ---------- Serial ----------
    def connect(self, port: str) -> None:
        self.disconnect()
        self.serial_port = open_serial_port(port)
        self._start_polling()

    def disconnect(self) -> None:
        self._stop_polling()
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception:
                pass
        self.serial_port = None

        # on désactive tout proprement côté soft
        for i in range(self.max_devices):
            self._mfc_objs[i] = None
            self.devices[i].active = False

    # ---------- Device lifecycle ----------
    def activate(self, idx: int) -> None:
        d = self._get(idx)
        if not self.serial_port or not self.serial_port.is_open:
            raise RuntimeError("Port série non connecté")

        try:
            mfc = device.mfc(self.serial_port)
            mfc.tag_name = pack_tag_name(d.tag)

            with self.serial_lock:
                mfc.get_address()

            d.active = True
            self._mfc_objs[idx] = mfc

            # gaz
            d.available_gases.clear()
            d.gas_map.clear()
            for gaz_id in range(1, 5):
                try:
                    with self.serial_lock:
                        mfc.Select_gaz(gaz_id)
                        raw = mfc.Select_nom(gaz_id)
                    name = raw.split(b"\x00")[0].decode("ascii", errors="ignore")
                    if name:
                        d.available_gases.append(name)
                        d.gas_map[name] = gaz_id
                except Exception:
                    pass

            if d.available_gases:
                first = d.available_gases[0]
                with self.serial_lock:
                    mfc.Select_gaz(d.gas_map[first])
                d.selected_gas = d.gas_map[first]

            with self.serial_lock:
                mfc.write_totalizer_control(1)

            # ramp (par défaut OFF)
            self.apply_ramp_settings(idx, ramp_active=d.ramp_active, ramp_time_s=d.ramp_time_s)

            # vanne régulation par défaut + consigne 0
            self.set_vanne(idx, "Régulation")
            self.send_consigne(idx, 0.0)

        except Exception as e:
            d.active = False
            self._mfc_objs[idx] = None
            log.exception("Erreur activation device %s: %s", idx + 1, e)
            raise

    def deactivate(self, idx: int) -> None:
        d = self._get(idx)
        mfc = self._mfc_objs[idx]
        if d.active and mfc:
            try:
                self.send_consigne(idx, 0.0)
                time.sleep(0.2)
                with self.serial_lock:
                    mfc.write_ramp_control(0)
            except Exception:
                pass
        d.active = False
        self._mfc_objs[idx] = None
        self._reset_data(d)

    # ---------- Commands ----------
    def set_tag(self, idx: int, tag: str) -> None:
        d = self._get(idx)
        d.tag = str(tag)[:8].ljust(8, "_")
        # si actif, il faudrait ré-instancier le mfc (simple: désactiver/activer)
        # on laisse l’UI gérer (OFF puis ON)

    def send_consigne(self, idx: int, consigne: float) -> None:
        d = self._get(idx)
        mfc = self._need_mfc(idx)

        # clamp
        try:
            c = float(consigne)
        except Exception:
            return
        if c < 0:
            c = 0.0
        if d.full_scale_value and c > d.full_scale_value:
            c = d.full_scale_value

        d.consigne = c

        if not d.full_scale_value:
            # on tentera au prochain poll (quand FS connu)
            return

        perc = (d.consigne / d.full_scale_value) * 100.0
        with self.serial_lock:
            mfc.write_setpoint(perc, units=57)

        now = datetime.datetime.now()
        d.consigne_points = (d.consigne_points + [(d.consigne, now)])[-3600:]

    def set_vanne(self, idx: int, action: str) -> None:
        d = self._get(idx)
        mfc = self._need_mfc(idx)

        cmd = {"Ouverture": 1, "Fermeture": 2, "Régulation": 0}.get(action)
        if cmd is None:
            return
        with self.serial_lock:
            mfc.set_vanne(cmd)
            d.valve_command = mfc.red_vanne() or "N/A"

    def reset_totalization(self, idx: int) -> None:
        d = self._get(idx)
        mfc = self._need_mfc(idx)
        with self.serial_lock:
            mfc.write_totalizer_control(2)
        d.totalization_value = (0, d.totalization_value[1] if d.totalization_value else "N/A")

    def apply_ramp_settings(self, idx: int, ramp_active: bool, ramp_time_s: float) -> None:
        d = self._get(idx)
        mfc = self._need_mfc(idx)

        d.ramp_active = bool(ramp_active)
        try:
            d.ramp_time_s = float(ramp_time_s)
        except Exception:
            d.ramp_time_s = 1.0
        if d.ramp_time_s <= 0:
            d.ramp_time_s = 1.0

        with self.serial_lock:
            if not d.ramp_active:
                mfc.write_ramp_control(0)
            else:
                mfc.write_ramp_control(4)  # linear up/down
                mfc.write_linear_ramp_value(d.ramp_time_s)

    def select_gas(self, idx: int, gas_name: str) -> None:
        d = self._get(idx)
        mfc = self._need_mfc(idx)

        gaz_id = d.gas_map.get(gas_name)
        if gaz_id is None:
            return
        with self.serial_lock:
            mfc.Select_gaz(gaz_id)
        d.selected_gas = gaz_id

    # ---------- Polling ----------
    def _start_polling(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _stop_polling(self) -> None:
        self._poll_stop.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)

    def _poll_loop(self) -> None:
        while not self._poll_stop.is_set():
            for i in range(self.max_devices):
                d = self.devices[i]
                if not d.active:
                    continue
                try:
                    self._poll_one(i)
                except Exception:
                    self._reset_data(d)
            time.sleep(1.0)

    def _poll_one(self, idx: int) -> None:
        d = self._get(idx)
        mfc = self._need_mfc(idx)

        if d.selected_gas is None:
            # si pas défini, on tente un défaut
            if d.available_gases:
                d.selected_gas = d.gas_map.get(d.available_gases[0])
            if d.selected_gas is None:
                return

        g = d.selected_gas
        with self.serial_lock:
            fr = mfc.read_flow_rate(g) or (0, "N/A")
            tmp = mfc.read_dynamic() or (0, "N/A")
            fs = mfc.read_full_scale_flow_rate(g) or (0, "N/A")
            tot = mfc.read_totalizer_value() or (0, "N/A")
            valve = mfc.red_vanne() or "N/A"

        d.mesure = (fr[0], fr[1])
        d.temperature = (tmp[0], tmp[1])
        d.full_scale_value = float(fs[0] or 0)
        d.full_scale = (fs[0], fs[1])
        d.totalization_value = (tot[0], tot[1])
        d.valve_command = valve

        now = datetime.datetime.now()
        try:
            mv = float(d.mesure[0])
        except Exception:
            mv = 0.0

        d.measurements = (d.measurements + [(mv, now)])[-3600:]
        d.consigne_points = (d.consigne_points + [(float(d.consigne), now)])[-3600:]

        # si on a appris FS juste maintenant, on peut pousser la consigne %
        if d.full_scale_value and d.consigne:
            # renvoie la consigne (en %) à partir de la valeur
            try:
                self.send_consigne(idx, d.consigne)
            except Exception:
                pass

    def snapshot(self) -> Dict[str, Any]:
        return {
            "connected": bool(self.serial_port and self.serial_port.is_open),
            "devices": [
                {
                    "index": d.index,
                    "tag": d.tag,
                    "active": d.active,
                    "consigne": d.consigne,
                    "full_scale_value": d.full_scale_value,
                    "mesure": {"value": d.mesure[0], "unit": d.mesure[1]},
                    "total": {"value": d.totalization_value[0], "unit": d.totalization_value[1]},
                    "valve": d.valve_command,
                    "ramp": {"active": d.ramp_active, "time_s": d.ramp_time_s},
                    "gases": d.available_gases,
                    "selected_gas": d.selected_gas,
                }
                for d in self.devices
            ],
        }

    # ---------- helpers ----------
    def _get(self, idx: int) -> DeviceState:
        if not (0 <= idx < self.max_devices):
            raise IndexError("device index out of range")
        return self.devices[idx]

    def _need_mfc(self, idx: int):
        d = self._get(idx)
        mfc = self._mfc_objs[idx]
        if not d.active or mfc is None:
            raise RuntimeError("Device OFF")
        return mfc

    def _reset_data(self, d: DeviceState) -> None:
        d.mesure = (0, "N/A")
        d.temperature = (0, "N/A")
        d.full_scale = (0, "N/A")
        d.valve_command = "N/A"
        d.measurements.clear()
        d.consigne_points.clear()
        d.totalization_value = (0, "N/A")
