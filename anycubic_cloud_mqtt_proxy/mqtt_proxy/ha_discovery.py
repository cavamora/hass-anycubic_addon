import json
import logging
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
    ) -> None:
        self.local_client = local_client
        self.local_prefix = local_prefix
        self.LOG = logger
        self.printers_by_key = printers_by_key
        self.printer_objects_by_key = printer_objects_by_key

    def _ha_sensor_config_topic(self, printer_key: str) -> str:
        return f"homeassistant/sensor/anycubic_{printer_key}_status/config"

    def _ha_sensor_state_topic(self, printer_key: str) -> str:
        return f"{self.local_prefix}/printers/{printer_key}/status"

    def _ha_online_config_topic(self, printer_key: str) -> str:
        return f"homeassistant/binary_sensor/anycubic_{printer_key}_online/config"

    def _ha_online_state_topic(self, printer_key: str) -> str:
        return f"{self.local_prefix}/printers/{printer_key}/online"

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

    def update_from_cloud(self) -> None:
        try:
            for key, pobj in self.printer_objects_by_key.items():
                try:
                    self.printers_by_key[key]["status"] = getattr(pobj, "current_status", "unknown")
                except Exception:
                    pass
            self.publish_all_printer_status()
            self.publish_all_printer_online()
        except Exception as e:
            self.LOG.error("Erro ao processar atualização de status das impressoras: %s", e)
