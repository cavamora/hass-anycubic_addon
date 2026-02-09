ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG C.UTF-8

# Instala Python em imagens base Alpine dos add-ons
RUN apk add --no-cache python3 py3-pip

WORKDIR /opt

# Código do proxy
COPY mqtt_proxy/ /opt/mqtt_proxy/

# Biblioteca Anycubic (reutilizada da integração)
COPY ../../custom_components/anycubic_cloud/anycubic_cloud_api /opt/anycubic_cloud_api

# Dependências Python
RUN pip3 install --no-cache-dir -r /opt/mqtt_proxy/requirements.txt

# Scripts s6 para iniciar serviço
COPY rootfs/ /

