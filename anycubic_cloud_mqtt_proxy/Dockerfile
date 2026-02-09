ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8

# Instala Python em imagens base Alpine dos add-ons
RUN apk add --no-cache python3 py3-pip

WORKDIR /opt

# Criar virtualenv para contornar PEP 668 (externally managed)
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Código do proxy
COPY mqtt_proxy/ /opt/mqtt_proxy/

# Biblioteca Anycubic (reutilizada da integração)
# Biblioteca Anycubic (agora dentro deste repositório)
COPY mqtt_proxy/anycubic_cloud_api /opt/anycubic_cloud_api

# Dependências Python (instalar no venv)
RUN /opt/venv/bin/pip install --upgrade pip setuptools wheel \
	&& /opt/venv/bin/pip install --no-cache-dir -r /opt/mqtt_proxy/requirements.txt

# Scripts s6 para iniciar serviço
COPY rootfs/ /

# Garantir permissão de execução do script s6
RUN chmod +x /etc/services.d/mqtt-proxy/run

