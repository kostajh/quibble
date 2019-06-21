# Copyright 2017-2018, Antoine "hashar" Musso
# Copyright 2017, Tyler Cipriani
# Copyright 2017-2018, Wikimedia Foundation Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.

FROM docker-registry.wikimedia.org/releng/node10-test:latest as node10-test
FROM docker-registry.wikimedia.org/releng/ci-stretch:latest

ARG DEBIAN_FRONTEND=noninteractive

# See <https://docs.npmjs.com/misc/config#environment-variables>
# and <https://docs.npmjs.com/cli/cache>
ENV NPM_CONFIG_CACHE=/cache/npm
ENV BABEL_CACHE_PATH=$XDG_CACHE_HOME/babel-cache.json

# CI utilities
RUN git clone --depth=1 "https://gerrit.wikimedia.org/r/p/integration/composer" "/srv/deployment/integration/composer" && \
    rm -fR /srv/deployment/integration/composer/.git && \
	ln -s "/srv/deployment/integration/composer/vendor/bin/composer" "/usr/local/bin/composer"

RUN apt-get update \
    && apt-get install -y python3 python3-setuptools python3-pip

RUN apt-get update \
    && : "Zuul cloner dependencies" \
    && apt-get install -y \
        python3-extras \
        python3-six \
        python3-yaml \
        python3-git \
    && rm -fR /cache/pip

RUN apt-get update \
    && : "Composer/MediaWiki related dependencies" \
    && apt-get install -y \
        php-apcu \
        php-cli \
        php-curl \
        php-gd \
        php-intl \
        php-mbstring \
        php-mysql \
        php-sqlite3 \
        php-tidy \
        php-xml \
        php-zip \
        php-fpm \
        djvulibre-bin \
        imagemagick \
        libimage-exiftool-perl \
        mariadb-server \
        apache2 \
        python \
        ffmpeg \
        build-essential \
        nodejs-legacy \
        tidy \
    && : "Xvfb" \
    && apt-get install -y \
        xvfb \
        xauth \
    && apt-get purge -y python3-pip \
    && rm -fR /cache/pip

COPY --from=node10-test /srv/npm/ /srv/npm
RUN ln -s /srv/npm/bin/npm-cli.js /usr/local/bin/npm

RUN apt-get update \
    && apt-get install -y \
        chromedriver \
        chromium

RUN apt-get autoremove -y --purge \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/quibble

RUN cd /opt/quibble && \
    python3 setup.py install && \
    rm -fR /opt/quibble /cache/pip

# Restart so that Apache knows to process PHP files.
RUN a2enmod proxy_fcgi \
  && a2enmod mpm_event \
  && a2enmod rewrite \
  && a2enmod http2 \
  && a2enmod cache
COPY ./quibble/php-fpm/php-fpm.conf /etc/php/7.0/fpm/php-fpm.conf
COPY ./quibble/php-fpm/www.conf /etc/php/7.0/fpm/pool.d/www.conf
RUN mkdir /tmp/php && chown -R nobody:nogroup /tmp/php
RUN touch /tmp/php7.0-fpm.log /tmp/php/php7.0-fpm.pid \
  && chown nobody:nogroup /tmp/php7.0-fpm.log /tmp/php/php7.0-fpm.pid
RUN service apache2 restart

RUN echo 'opcache.validate_timestamps=0\n\
opcache.file_update_protection=0\n\
opcache.memory_consumption=256\n\
opcache.max_accelerated_files=24000\n\
opcache.max_wasted_percentage=10\n\
opcache.revalidate_freq=0\n\
opcache.fast_shutdown=1' > /etc/php/7.0/fpm/php.ini

RUN echo 'zlib.output_compression=On' >> /etc/php/7.0/fpm/php.ini

RUN service php7.0-fpm restart
COPY ./quibble/apache/ports.conf /etc/apache2/ports.conf
COPY ./quibble/apache/000-default.conf /etc/apache2/sites-available/000-default.conf
COPY ./quibble/apache/apache2.conf /etc/apache2/apache2.conf
COPY ./quibble/apache/envvars /etc/apache2/envvars

# Unprivileged
RUN install --directory /workspace --owner=nobody --group=nogroup
USER nobody
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/quibble"]
