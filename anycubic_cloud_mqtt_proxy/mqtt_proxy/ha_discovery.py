import json
import logging
import os
from typing import Any

from paho.mqtt import client as mqtt_client


class HADiscoveryPublisher:
    def __init__(
        self,
        local_client: mqtt_client.Client | None,
        local_prefix: str,
        logger: logging.Logger,
        printers_by_key: dict[str, dict[str, Any]],
        printer_objects_by_key: dict[str, Any],
        cache_path: str | None = None,
    ) -> None:
        self.local_client = local_client
        self.local_prefix = local_prefix
        self.LOG = logger
        self.printers_by_key = printers_by_key
        self.printer_objects_by_key = printer_objects_by_key
        self.cache_path = cache_path or "/data/anycubic_proxy_cache.json"
        self._cache: dict[str, Any] = {}

    # Cache helpers
    def load_cache(self) -> None:
        try:
            if os.path.exists(self.cache_path):
                with open(self.cache_path, "r") as f:
                    self._cache = json.load(f)
                self.LOG.info("Cache de estados carregado: %s", self.cache_path)
        except Exception as e:
            self.LOG.warning("Falha ao carregar cache de estados (%s): %s", self.cache_path, e)
            self._cache = {}

    def save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump(self._cache, f)
        except Exception as e:
            self.LOG.warning("Falha ao salvar cache de estados (%s): %s", self.cache_path, e)

    def _ha_sensor_config_topic(self, printer_key: str) -> str:
        return f"homeassistant/sensor/anycubic_{printer_key}_status/config"

    def _ha_sensor_state_topic(self, printer_key: str) -> str:
        return f"{self.local_prefix}/printers/{printer_key}/status"

    def _ha_online_config_topic(self, printer_key: str) -> str:
        return f"homeassistant/binary_sensor/anycubic_{printer_key}_online/config"

    def _ha_online_state_topic(self, printer_key: str) -> str:
        return f"{self.local_prefix}/printers/{printer_key}/online"

    def _ha_ace_config_topic(self, printer_key: str, box_index: int) -> str:
        # box_index 0 -> Ace Pro 1, 1 -> Ace Pro 2
        human_idx = box_index + 1
        return f"homeassistant/sensor/anycubic_{printer_key}_ace_pro_{human_idx}_spools/config"

    def _ha_ace_state_topic(self, printer_key: str, box_index: int) -> str:
        human_idx = box_index + 1
        return f"{self.local_prefix}/printers/{printer_key}/ace_pro/{human_idx}/state"

    def _ha_ace_attrs_topic(self, printer_key: str, box_index: int) -> str:
        human_idx = box_index + 1
        return f"{self.local_prefix}/printers/{printer_key}/ace_pro/{human_idx}/attrs"

    def _publish_ha_discovery_for_printer(self, pinfo: dict[str, Any]) -> None:
        if not self.local_client:
            return
        key = str(pinfo.get("key"))
        name = pinfo.get("name") or pinfo.get("model") or f"Anycubic {key}"
        device = {
            "identifiers": [f"anycubic_{key}"],
            "name": name,
            "manufacturer": "Anycubic",
            "model": pinfo.get("model") or "Printer",
        }

        payload_status = {
            "name": f"{name} Status",
            "unique_id": f"anycubic_{key}_status",
            "state_topic": self._ha_sensor_state_topic(key),
            "icon": "mdi:printer-3d",
            "device": device,
        }
        topic = self._ha_sensor_config_topic(key)
        try:
            self.LOG.info("Publicando discovery HA (sensor status): %s", topic)
            self.local_client.publish(topic, json.dumps(payload_status), qos=0, retain=True)
        except Exception as e:
            self.LOG.error("Falha ao publicar discovery HA para %s: %s", key, e)

        payload_online = {
            "name": f"{name} Online",
            "unique_id": f"anycubic_{key}_online",
            "state_topic": self._ha_online_state_topic(key),
            "device_class": "connectivity",
            "payload_on": "online",
            "payload_off": "offline",
            "device": device,
        }
        online_topic = self._ha_online_config_topic(key)
        try:
            self.LOG.info("Publicando discovery HA (sensor online): %s", online_topic)
            self.local_client.publish(online_topic, json.dumps(payload_online), qos=0, retain=True)
        except Exception as e:
            self.LOG.error("Falha ao publicar discovery HA online para %s: %s", key, e)

    def publish_ha_discovery(self) -> None:
        for key, info in self.printers_by_key.items():
            self._publish_ha_discovery_for_printer(info)
            # Publica sensores Ace Pro 1 e Ace Pro 2
            try:
                name = info.get("name") or info.get("model") or f"Anycubic {key}"
                for idx in [0, 1]:
                    human_idx = idx + 1
                    sensor_name = f"{name} Ace Pro {human_idx} Spools"
                    payload_ace = {
                        "name": sensor_name,
                        "unique_id": f"anycubic_{key}_ace_pro_{human_idx}_spools",
                        "state_topic": self._ha_ace_state_topic(key, idx),
                        "json_attributes_topic": self._ha_ace_attrs_topic(key, idx),
                        "icon": "mdi:palette",
                        "device": {
                            "identifiers": [f"anycubic_{key}"],
                            "name": name,
                            "manufacturer": "Anycubic",
                            "model": info.get("model") or "Printer",
                        },
                    }
                    topic_ace = self._ha_ace_config_topic(key, idx)
                    self.LOG.info("Publicando discovery HA (Ace Pro %s): %s", human_idx, topic_ace)
                    self.local_client and self.local_client.publish(topic_ace, json.dumps(payload_ace), qos=0, retain=True)
            except Exception as e:
                self.LOG.error("Falha ao publicar discovery Ace Pro para %s: %s", key, e)

    def _publish_printer_status(self, printer_key: str) -> None:
        if not self.local_client:
            return
        topic = self._ha_sensor_state_topic(printer_key)
        status = self.printers_by_key.get(printer_key, {}).get("status", "unknown")
        try:
            self.LOG.info("Atualizando estado da impressora %s: %s", printer_key, status)
            self.local_client.publish(topic, status, qos=0, retain=True)
        except Exception as e:
            self.LOG.error("Falha ao publicar estado %s para %s: %s", status, printer_key, e)

    def publish_all_printer_status(self) -> None:
        for key in self.printers_by_key.keys():
            self._publish_printer_status(key)

    def _collect_ace_attrs(self, printer_key: str, box_index: int) -> dict[str, Any] | None:
        pobj = self.printer_objects_by_key.get(printer_key)
        if pobj is None:
            return None
        mcb_list = getattr(pobj, "multi_color_box", None)
        if not mcb_list or len(mcb_list) <= box_index:
            return None
        mcb = mcb_list[box_index]
        try:
            spool_info = mcb.spool_info_object
            attrs = {
                "box_id": mcb.box_id,
                "is_connected": mcb.is_connected,
                "loaded_slot": getattr(mcb, "_loaded_slot", None),
                "slots_count": mcb.total_slots,
                "spool_info": spool_info or [],
                "temperature": mcb.current_temperature,
                "humidity": getattr(mcb, "current_humidity", 0),
                "auto_feed": mcb.auto_feed,
            }
            # Drying status may be complex; include simplified if present
            try:
                ds = mcb.drying_status
                if ds is not None:
                    attrs["drying"] = {
                        "on": getattr(ds, "is_drying", False),
                        "status_code": getattr(ds, "raw_status_code", None),
                        "target_temperature": getattr(ds, "target_temperature", 0),
                        "total_duration": getattr(ds, "total_duration", 0),
                        "remaining_time": getattr(ds, "remaining_time", 0),
                    }
            except Exception:
                pass
            return attrs
        except Exception as e:
            self.LOG.debug("Falha ao coletar atributos Ace Pro %s para %s: %s", box_index + 1, printer_key, e)
            return None

    def _publish_ace_state_and_attrs(self, printer_key: str, box_index: int) -> None:
        if not self.local_client:
            return
        attrs = self._collect_ace_attrs(printer_key, box_index)
        pobj = self.printer_objects_by_key.get(printer_key)
        state = "inactive"
        try:
            mcb_list = getattr(pobj, "multi_color_box", None) if pobj else None
            if mcb_list and len(mcb_list) > box_index:
                state = "active" if mcb_list[box_index].is_connected else "inactive"
        except Exception:
            pass
        try:
            self.local_client.publish(self._ha_ace_state_topic(printer_key, box_index), state, qos=0, retain=True)
            if attrs is not None:
                self.local_client.publish(self._ha_ace_attrs_topic(printer_key, box_index), json.dumps(attrs), qos=0, retain=True)
            # Atualiza cache
            self._cache.setdefault(printer_key, {})
            self._cache[printer_key].setdefault("ace", {})
            self._cache[printer_key]["ace"][str(box_index)] = {
                "state": state,
                "attrs": attrs or {},
            }
        except Exception as e:
            self.LOG.error("Falha ao publicar Ace Pro %s para %s: %s", box_index + 1, printer_key, e)

    def _publish_printer_online(self, printer_key: str) -> None:
        if not self.local_client:
            return
        topic = self._ha_online_state_topic(printer_key)
        online_val = "unknown"
        try:
            pobj = self.printer_objects_by_key.get(printer_key)
            if pobj is not None:
                online_val = "online" if getattr(pobj, "printer_online", False) else "offline"
        except Exception:
            pass
        try:
            self.LOG.info("Atualizando online da impressora %s: %s", printer_key, online_val)
            self.local_client.publish(topic, online_val, qos=0, retain=True)
        except Exception as e:
            self.LOG.error("Falha ao publicar online %s para %s: %s", online_val, printer_key, e)

    def publish_all_printer_online(self) -> None:
        for key in self.printers_by_key.keys():
            self._publish_printer_online(key)

    def publish_all_ace(self) -> None:
        for key in self.printers_by_key.keys():
            # Suporta até duas unidades Ace Pro
            for idx in [0, 1]:
                self._publish_ace_state_and_attrs(key, idx)
        # Salva cache após publicar tudo
        self.save_cache()

    def publish_ace_from_cache(self) -> None:
        if not self.local_client:
            return
        # Publica estados/atributos do cache, se presentes
        try:
            for key in self.printers_by_key.keys():
                ace_cache = (self._cache.get(key) or {}).get("ace") or {}
                for idx in [0, 1]:
                    box_key = str(idx)
                    if box_key in ace_cache:
                        cached = ace_cache[box_key]
                        state = cached.get("state", "unknown")
                        attrs = cached.get("attrs")
                        self.local_client.publish(self._ha_ace_state_topic(key, idx), state, qos=0, retain=True)
                        if attrs is not None:
                            self.local_client.publish(self._ha_ace_attrs_topic(key, idx), json.dumps(attrs), qos=0, retain=True)
        except Exception as e:
            self.LOG.warning("Falha ao publicar Ace Pro a partir do cache: %s", e)

    def update_from_cloud(self) -> None:
        try:
            for key, pobj in self.printer_objects_by_key.items():
                try:
                    self.printers_by_key[key]["status"] = getattr(pobj, "current_status", "unknown")
                except Exception:
                    pass
            self.publish_all_printer_status()
            self.publish_all_printer_online()
            self.publish_all_ace()
        except Exception as e:
            self.LOG.error("Erro ao processar atualização de status das impressoras: %s", e)
