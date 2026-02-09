# Anycubic Cloud MQTT Proxy (Home Assistant Add-on)

Este add-on funciona como um proxy entre o MQTT da nuvem da Anycubic e o MQTT local (tipicamente o `core-mosquitto` do Home Assistant). Ele:

- NÃO publica nada automaticamente.
- Escuta mensagens vindas da nuvem e as repassa para o broker local com um prefixo.
- Escuta tópicos locais específicos para repassar comandos para a nuvem.
- Centraliza a autenticação Anycubic (acesso via `auth_token` ou `access_token`).
- Adiciona logs detalhados para depuração.

## Instalação local

1. Copie a pasta `addons/anycubic_cloud_mqtt_proxy` para o diretório de add-ons locais do seu Home Assistant.
2. No Supervisor, adicione o repositório local (se aplicável) e instale o add-on.
3. Configure as opções:
   - `auth_mode`: `android` ou `slicer`.
   - `auth_token`: token de usuário (Android) ou deixe vazio se usar `access_token` no modo `slicer`.
   - `access_token`: token de acesso (modo slicer), se preferir.
   - `device_id`: opcional (Android). Se vazio, o app gera um automaticamente.
   - `local_mqtt.host`: normalmente `core-mosquitto`.
   - `local_mqtt.base_topic`: prefixo local para mensagens espelhadas, padrão `anycubic_cloud_proxy`.
   - `ssl_cert_dir`: caminho onde você colocará os certificados TLS da Anycubic (ver abaixo).

4. Certificados TLS Anycubic (necessários para o MQTT da nuvem):
   - Coloque os arquivos `anycubic_mqqt_tls_ca.crt`, `anycubic_mqqt_tls_client.crt`, `anycubic_mqqt_tls_client.key` em `/data/ssl/anycubic` do add-on (ou ajuste `ssl_cert_dir`).

## Tópicos e fluxo

- Nuvem → Local: mensagem recebida da nuvem é publicada em:
  - `<base_topic>/cloud/<topico_original_da_nuvem>`

- Local → Nuvem (duas formas):
  1. Raw: publique em `anycubic_cloud_proxy/to_cloud/raw` um JSON:
     ```json
     { "topic": "anycubic/anycubicCloud/v1/printer/public/<machine_type>/<printer_key>/<endpoint>", "payload": { ... } }
     ```
     O proxy valida o prefixo permitido e repassa.

  2. Publish por chave: publique em `anycubic_cloud_proxy/to_cloud/publish/{printer_key}/{endpoint}` com payload JSON; o proxy monta o tópico de publicação conforme `machine_type`/`key` da impressora e repassa.

> Observação: Por segurança, apenas tópicos com prefixo `anycubic/anycubicCloud/v1/printer/public/` são repassados para a nuvem.

## Logs

- O add-on registra tudo que importa (`INFO`) e erros detalhados.
- Ajuste `log_level` para `DEBUG` para inspecionar dados e mapeamentos.

## Desenvolvimento

- O Dockerfile copia a biblioteca `anycubic_cloud_api` desta integração para dentro do container do add-on.
- Dependências Python estão em `mqtt_proxy/requirements.txt`.

