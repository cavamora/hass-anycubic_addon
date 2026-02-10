import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any

import aiohttp
from paho.mqtt import client as mqtt_client

# Ajusta caminho para importar a lib reutilizada
sys.path.append("/opt")
from anycubic_cloud_api.anycubic_api import AnycubicMQTTAPI, AnycubicAPI  # type: ignore
from anycubic_cloud_api.models.auth import AnycubicAuthMode  # type: ignore


LOG = logging.getLogger("anycubic_proxy")


def load_options() -> dict[str, Any]:
    """Carrega opções do add-on do arquivo padrão do Supervisor."""
    options_path = "/data/options.json"
    try:
        with open(options_path, "r") as f:
            return json.load(f)
    except Exception as e:
        LOG.error("Falha ao ler %s: %s", options_path, e)
        return {}


class ProxyService:
    def __init__(self, opts: dict[str, Any]) -> None:
        self.opts = opts
        log_level = opts.get("log_level", "INFO").upper()
        logging.basicConfig(level=getattr(logging, log_level, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

        self.local_cfg = opts.get("local_mqtt", {})
        # Aliases top-level para facilitar configuração do usuário
        alias_user = opts.get("local_mqtt_username")
        alias_pass = opts.get("local_mqtt_password")
        if alias_user:
            self.local_cfg["username"] = alias_user
        if alias_pass:
            self.local_cfg["password"] = alias_pass
        self.local_prefix: str = self.local_cfg.get("base_topic", "anycubic_cloud_proxy")
        self.allow_prefix: str = opts.get("allow_publish_prefix", "anycubic/anycubicCloud/v1/printer/public/")
        self.local_subs: list[str] = opts.get("subscribe_local_topics", [f"{self.local_prefix}/to_cloud/raw", f"{self.local_prefix}/to_cloud/publish/#"])  # noqa: E501
        self.ssl_cert_dir: str = opts.get("ssl_cert_dir", "/ssl/anycubic")
        # Fallback automático: se diretório configurado não existir, tenta /ssl/anycubic
        try:
            if not os.path.exists(self.ssl_cert_dir) and os.path.exists("/ssl/anycubic"):
                LOG.info("Diretório de certificados não encontrado em %s; usando /ssl/anycubic.", self.ssl_cert_dir)
                self.ssl_cert_dir = "/ssl/anycubic"
        except Exception:
            pass

        self._stop_event = threading.Event()

        # MQTT local
        self.local_client: mqtt_client.Client | None = None

        # Anycubic MQTT + API (inicializados em async_setup)
        self.session: aiohttp.ClientSession | None = None
        self.cookies: aiohttp.CookieJar | None = None
        self.api: AnycubicMQTTAPI | None = None

        # Printer map por key
        self.printers_by_key: dict[str, dict[str, Any]] = {}
        # Objetos de impressora para estados detalhados
        self.printer_objects_by_key: dict[str, Any] = {}

    def _on_local_connect(self, client: mqtt_client.Client, userdata: Any, flags: dict[str, Any], rc: int) -> None:
        if rc == 0:
            LOG.info("Conectado ao MQTT local com sucesso.")
            # Subscrever tópicos somente após conexão bem-sucedida
            for sub in self.local_subs:
                LOG.info("Subscribing local: %s", sub)
                client.subscribe(sub)
        else:
            LOG.error("Falha ao conectar ao MQTT local. rc=%s", rc)

    def _on_local_disconnect(self, client: mqtt_client.Client, userdata: Any, rc: int) -> None:
        LOG.warning("Desconectado do MQTT local. rc=%s", rc)

    def _auth_mode(self) -> AnycubicAuthMode:
        # Força modo SLICER para usar apenas access_token do Anycubic Slicer
        return AnycubicAuthMode.SLICER

    async def setup_auth(self) -> None:
        """Configura autenticação e valida tokens."""
        auth_mode = self._auth_mode()
        access_token = self.opts.get("access_token") or None

        # Criar sessão e API dentro de função assíncrona
        self.session = aiohttp.ClientSession()
        self.cookies = aiohttp.CookieJar()
        self.api = AnycubicMQTTAPI(
            session=self.session,
            cookie_jar=self.cookies,
            debug_logger=LOG,
            auth_mode=auth_mode,
        )
        # Desativar espelho de todas as mensagens por padrão
        self.api.set_mqtt_log_all_messages(False)

        self.api.set_authentication(
            auth_token=None,
            auth_mode=auth_mode,
            device_id=None,
            auth_access_token=access_token,
            auto_pick_token=True,
        )

        # Valida e obtém user info
        ok = await self.api.check_api_tokens()
        if not ok:
            raise RuntimeError("Falha de autenticação na API Anycubic. Informe um access_token válido do Anycubic Slicer.")
        await self.api.get_user_info()
        LOG.info("Autenticado na Anycubic Cloud como %s", self.api.anycubic_auth.api_user_identifier)

    async def load_printers(self) -> None:
        """Carrega impressoras do usuário para montar o mapeamento."""
        if not self.api:
            raise RuntimeError("API não inicializada")
        printers = await self.api.list_my_printers(ignore_init_errors=True)
        LOG.info("Encontradas %d impressoras.", len(printers))
        self.printers_by_key.clear()
        self.printer_objects_by_key.clear()
        for p in printers:
            if p and p.key:
                self.printers_by_key[p.key] = {
                    "id": p.id,
                    "name": p.name,
                    "machine_type": p.machine_type,
                    "key": p.key,
                    "model": getattr(p, "model", None),
                    "status": getattr(p, "current_status", "unknown"),
                }
                self.printer_objects_by_key[p.key] = p
                # Assina tópicos de status MQTT para esta impressora
                try:
                    if self.api is not None:
                        self.api.mqtt_add_subscribed_printer(p)
                except Exception as e:
                    LOG.error("Falha ao registrar assinatura MQTT da impressora %s: %s", p.key, e)
                # Loga informações detalhadas da impressora, quando disponíveis
                try:
                    fw_ver = p.fw_version.firmware_version if getattr(p, "fw_version", None) else None
                    fw_update_avail = p.fw_version.update_available if getattr(p, "fw_version", None) else False
                    LOG.info(
                        "Impressora carregada: id=%s key=%s modelo=%s nome=%s online=%s status=%s fw=%s upd_disp=%s mac=%s material=%s prints=%s tempo_total=%s",
                        p.id,
                        p.key,
                        getattr(p, "model", None),
                        p.name,
                        getattr(p, "printer_online", False),
                        getattr(p, "current_status", "unknown"),
                        fw_ver,
                        fw_update_avail,
                        getattr(p, "machine_mac", None),
                        getattr(p, "material_type", None),
                        getattr(p, "print_count", None),
                        getattr(p, "total_print_time_dhm_str", None),
                    )
                except Exception as e:
                    LOG.debug("Falha ao logar detalhes da impressora %s: %s", p.key, e)
        LOG.debug("Mapa de impressoras: %s", self.printers_by_key)

    def _ha_sensor_config_topic(self, printer_key: str) -> str:
        return f"homeassistant/sensor/anycubic_{printer_key}_status/config"

    def _ha_sensor_state_topic(self, printer_key: str) -> str:
        return f"{self.local_prefix}/printers/{printer_key}/status"

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
        payload = {
            "name": f"{name} Status",
            "unique_id": f"anycubic_{key}_status",
            "state_topic": self._ha_sensor_state_topic(key),
            "icon": "mdi:printer-3d",
            "device": device,
        }
        topic = self._ha_sensor_config_topic(key)
        try:
            LOG.info("Publicando discovery HA (sensor): %s", topic)
            self.local_client.publish(topic, json.dumps(payload), qos=0, retain=True)
        except Exception as e:
            LOG.error("Falha ao publicar discovery HA para %s: %s", key, e)

    def publish_ha_discovery(self) -> None:
        for key, info in self.printers_by_key.items():
            self._publish_ha_discovery_for_printer(info)

    def _publish_printer_status(self, printer_key: str) -> None:
        if not self.local_client:
            return
        topic = self._ha_sensor_state_topic(printer_key)
        status = self.printers_by_key.get(printer_key, {}).get("status", "unknown")
        try:
            LOG.info("Atualizando estado da impressora %s: %s", printer_key, status)
            self.local_client.publish(topic, status, qos=0, retain=True)
        except Exception as e:
            LOG.error("Falha ao publicar estado %s para %s: %s", status, printer_key, e)

    def publish_all_printer_status(self) -> None:
        for key in self.printers_by_key.keys():
            self._publish_printer_status(key)

    def _on_cloud_printer_update(self) -> None:
        # Atualiza snapshot de status e republica
        try:
            for key, pobj in self.printer_objects_by_key.items():
                try:
                    self.printers_by_key[key]["status"] = getattr(pobj, "current_status", "unknown")
                except Exception:
                    pass
            self.publish_all_printer_status()
        except Exception as e:
            LOG.error("Erro ao processar atualização de status das impressoras: %s", e)

    async def _async_bootstrap(self) -> None:
        """Inicializa autenticação e carrega impressoras em um único loop."""
        await self.setup_auth()
        await self.load_printers()
        # Fecha a sessão HTTP para evitar warnings de sessão não fechada
        try:
            if self.session:
                await self.session.close()
        except Exception:
            pass

    def _mirror_raw_to_local(self, topic: str, payload: str) -> None:
        """Publica mensagem crua recebida da nuvem no broker local."""
        if not self.local_client:
            return
        local_topic = f"{self.local_prefix}/cloud/{topic}"
        try:
            self.local_client.publish(local_topic, payload, qos=0, retain=False)
        except Exception as e:
            LOG.error("Falha ao publicar no MQTT local (%s): %s", local_topic, e)

    def _start_anycubic_mqtt(self) -> None:
        """Conecta ao MQTT Anycubic em uma thread dedicada."""
        def runner():
            try:
                # Callback para espelho de mensagens
                if self.api is not None:
                    self.api._mqtt_callback_mirror_raw_message = self._mirror_raw_to_local
                    self.api._mqtt_callback_printer_update = self._on_cloud_printer_update
                # Conecta e bloqueia até encerrar
                if self.api is not None:
                    self.api.connect_mqtt()
            except Exception as e:
                LOG.error("Erro no cliente MQTT Anycubic: %s", e)
        th = threading.Thread(target=runner, daemon=True)
        th.start()

    def _ensure_local_client(self) -> None:
        cfg = self.local_cfg
        cli = mqtt_client.Client(client_id=f"anycubic_proxy_{int(time.time())}")
        if cfg.get("username"):
            LOG.info("Usando usuário para MQTT local: %s", cfg.get("username"))
            cli.username_pw_set(cfg.get("username"), cfg.get("password") or None)
        cli.on_message = self._on_local_message
        cli.on_connect = self._on_local_connect
        cli.on_disconnect = self._on_local_disconnect
        host = cfg.get("host", "core-mosquitto")
        port = int(cfg.get("port", 1883))
        LOG.info("Conectando ao MQTT local em %s:%s", host, port)
        cli.connect(host, port, keepalive=60)
        cli.loop_start()
        self.local_client = cli

    def _on_local_message(self, client: mqtt_client.Client, userdata: Any, message: mqtt_client.MQTTMessage) -> None:
        topic = str(message.topic)
        raw = message.payload.decode("utf-8")
        try:
            if topic.endswith("/raw"):
                # Espera JSON {"topic": "<cloud_topic>", "payload": <obj|string>}
                data = json.loads(raw)
                cloud_topic = str(data.get("topic") or "")
                payload = data.get("payload")
                if not cloud_topic.startswith(self.allow_prefix):
                    LOG.warning("Negado repasse: tópico fora do prefixo permitido: %s", cloud_topic)
                    return
                mqtt_payload = json.dumps(payload) if isinstance(payload, dict) else str(payload)
                if self.api._mqtt_client is not None:
                    LOG.info("Repasse local→nuvem (raw): %s", cloud_topic)
                    self.api._mqtt_client.publish(cloud_topic, mqtt_payload)
                else:
                    LOG.error("Cliente MQTT da nuvem não conectado, não foi possível repassar.")

            elif "/to_cloud/publish/" in topic:
                # Formato: base/to_cloud/publish/{printer_key}/{endpoint}
                parts = topic.split("/")
                try:
                    idx = parts.index("publish")
                    printer_key = parts[idx + 1]
                    endpoint = "/".join(parts[idx + 2:])
                except Exception:
                    LOG.error("Tópico local inválido para publish: %s", topic)
                    return
                if printer_key not in self.printers_by_key:
                    LOG.error("Printer key desconhecida: %s", printer_key)
                    return
                try:
                    payload_obj = json.loads(raw)
                except Exception:
                    payload_obj = raw
                # Constrói tópico de publicação para a impressora
                printer_info = self.printers_by_key[printer_key]
                full_topic = f"anycubic/anycubicCloud/v1/printer/public/{printer_info['machine_type']}/{printer_info['key']}/{endpoint}"
                if not full_topic.startswith(self.allow_prefix):
                    LOG.warning("Negado repasse: endpoint fora do prefixo permitido: %s", full_topic)
                    return
                mqtt_payload = json.dumps(payload_obj) if isinstance(payload_obj, dict) else str(payload_obj)
                if self.api._mqtt_client is not None:
                    LOG.info("Repasse local→nuvem (publish): %s", full_topic)
                    self.api._mqtt_client.publish(full_topic, mqtt_payload)
                else:
                    LOG.error("Cliente MQTT da nuvem não conectado, não foi possível repassar.")

            else:
                LOG.debug("Ignorando tópico local não tratado: %s", topic)

        except Exception as e:
            LOG.error("Erro processando mensagem local (%s): %s", topic, e)

    def run(self) -> None:
        # Verifica e prepara certificados (linka para o local esperado pela lib)
        ca = os.path.join(self.ssl_cert_dir, "anycubic_mqqt_tls_ca.crt")
        crt = os.path.join(self.ssl_cert_dir, "anycubic_mqqt_tls_client.crt")
        key = os.path.join(self.ssl_cert_dir, "anycubic_mqqt_tls_client.key")
        lib_res_dir = "/opt/anycubic_cloud_api/resources"
        try:
            os.makedirs(lib_res_dir, exist_ok=True)
            def _ensure_link(src: str, dst_name: str) -> None:
                dst = os.path.join(lib_res_dir, dst_name)
                if os.path.exists(dst):
                    return
                if os.path.exists(src):
                    try:
                        os.symlink(src, dst)
                        LOG.info("Vinculado certificado: %s -> %s", src, dst)
                    except Exception as e:
                        LOG.warning("Falha ao criar symlink de certificado (%s → %s): %s", src, dst, e)
            _ensure_link(ca, "anycubic_mqqt_tls_ca.crt")
            _ensure_link(crt, "anycubic_mqqt_tls_client.crt")
            _ensure_link(key, "anycubic_mqqt_tls_client.key")
        except Exception as e:
            LOG.warning("Falha ao preparar diretório de certificados: %s", e)
        if not (os.path.exists(ca) and os.path.exists(crt) and os.path.exists(key)):
            LOG.warning(
                "Certificados TLS Anycubic não encontrados em %s. O cliente MQTT da nuvem pode falhar ao conectar.",
                self.ssl_cert_dir,
            )

        # Inicializa loop assíncrono para auth + printers
        import asyncio
        asyncio.run(self._async_bootstrap())

        # Prepara MQTT local e nuvem
        self._ensure_local_client()
        # Publica discovery e estados iniciais após conectar ao broker local
        self.publish_ha_discovery()
        self.publish_all_printer_status()
        self._start_anycubic_mqtt()

        LOG.info("Proxy iniciado. Escutando nuvem e tópicos locais para repasse.")

        # Aguarda sinal de parada
        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        LOG.info("Encerrando...")
        try:
            if self.local_client:
                self.local_client.loop_stop()
                self.local_client.disconnect()
            if self.session:
                import asyncio
                asyncio.run(self.session.close())
        except Exception:
            pass


def _signal_handler(service: ProxyService, *args):
    service._stop_event.set()


def main() -> None:
    opts = load_options()
    service = ProxyService(opts)
    signal.signal(signal.SIGTERM, lambda *_: _signal_handler(service))
    signal.signal(signal.SIGINT, lambda *_: _signal_handler(service))
    service.run()


if __name__ == "__main__":
    main()
