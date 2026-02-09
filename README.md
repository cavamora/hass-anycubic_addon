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

## Instalação via repositório (Add-on Store)

Pré-requisitos: use Home Assistant OS ou Supervised (o modo Container não suporta Add-ons do Supervisor).

1. Publique este projeto em um repositório Git (por ex. GitHub) contendo os arquivos do add-on na raiz.
   - Inclua `repository.json` na raiz com `name`, `url` e `maintainer`.
   - Garanta que o Dockerfile seja auto-contido: a biblioteca `anycubic_cloud_api` precisa estar presente no build (ver observação abaixo).
2. No Home Assistant: Abra Loja de Add-ons → menu (três pontos) → Repositórios → Adicionar repositório.
3. Cole a URL do seu repositório Git e confirme.
4. O add-on "Anycubic Cloud MQTT Proxy" deve aparecer na lista; instale e configure.

### Observação importante sobre `anycubic_cloud_api`

Este add-on reutiliza a biblioteca `anycubic_cloud_api` da integração. No `Dockerfile` atual, ela é copiada de um caminho relativo externo:

```
COPY ../../custom_components/anycubic_cloud/anycubic_cloud_api /opt/anycubic_cloud_api
```

Para que o repositório seja instalável por outras pessoas via Add-on Store, você deve:
- Incluir a pasta `anycubic_cloud_api` dentro deste repositório (por exemplo, em `mqtt_proxy/anycubic_cloud_api`) e ajustar o `Dockerfile` para copiá-la a partir daqui; OU
- Publicar `anycubic_cloud_api` como pacote Python e instalar via `pip` durante o build.

Sem essa biblioteca no build, o container falhará ao iniciar.

## Alternativa: Add-ons locais

Se preferir sem publicar em GitHub:
- Acesse o diretório de dados do Supervisor (via Samba/SSH) e copie este add-on para `/addons/anycubic_cloud_mqtt_proxy`.
- Ative Modo Avançado, vá em Loja de Add-ons → "Add-ons locais" → instale.

## Pós-instalação

- Gere/obtenha os certificados TLS da Anycubic e coloque-os em `/data/ssl/anycubic` do add-on.
- Verifique se o broker local (`core-mosquitto`) está ativo.
- Ajuste `log_level` para `DEBUG` ao testar integrações entre nuvem e tópicos locais.

## Segurança e privacidade

- Este repositório não contém tokens pessoais; `auth_token`, `access_token` e `device_id` são fornecidos em tempo de execução via opções do add-on e NÃO devem ser commitados.
- Os certificados TLS (arquivos `.crt`/`.key`) não são inclusos no repositório. Mantenha-os somente dentro do container (pasta `/data/ssl/anycubic`).
- A biblioteca `anycubic_cloud_api` inclui constantes públicas (ex.: `AC_KNOWN_*`) obtidas do cliente da Anycubic (IDs/versões). Elas não são credenciais do seu usuário, mas se preferir pode parametrizá-las via ambiente.
- O arquivo `.gitignore` previne o commit de arquivos sensíveis e de sistema.

