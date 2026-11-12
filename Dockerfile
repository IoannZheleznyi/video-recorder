FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        apache2 \
        libapache2-mod-wsgi-py3 \
        python3 \
        python3-venv \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web_service.py video_service.wsgi ./
COPY docker/apache/video-service.conf /etc/apache2/sites-available/video-service.conf
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh /etc/apache2/sites-available/video-service.conf \
    && chmod +x /usr/local/bin/entrypoint.sh \
    && a2enmod wsgi \
    && a2dissite 000-default \
    && a2ensite video-service \
    && ln -sf /dev/stdout /var/log/apache2/access.log \
    && ln -sf /dev/stderr /var/log/apache2/error.log \
    && ln -sf /dev/stdout /var/log/apache2/other_vhosts_access.log \
    && mkdir -p /app/uploads \
    && chown www-data:www-data /app/uploads

EXPOSE 80

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]