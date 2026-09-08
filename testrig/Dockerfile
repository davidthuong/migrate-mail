# Dovecot cho testrig. Dung debian + apt chu khong dung image dovecot dong san:
# bo cau hinh sinh ra o day giong het thu se gap tren mot VPS that, nen loi
# tim thay o day la loi that su co the gap luc chay production.
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends dovecot-imapd ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 5000 vmail \
 && useradd -u 5000 -g vmail -d /var/vmail -m -s /usr/sbin/nologin vmail

# 'src' hoac 'dst' -- hai dau co namespace khac nhau co y, xem README.
ARG SIDE=src
COPY ${SIDE}/dovecot.conf   /etc/dovecot/dovecot.conf
COPY ${SIDE}/users          /etc/dovecot/users
COPY ${SIDE}/master-users   /etc/dovecot/master-users

# Chung chi cho cong 993. Chay ./make-certs.sh TRUOC khi build, neu khong buoc
# COPY nay se hong ngay -- co y de hong o day chu khong de Dovecot chet luc
# khoi dong voi mot dong loi kho doc hon.
COPY certs/${SIDE}.crt      /etc/dovecot/tls/server.crt
COPY certs/${SIDE}.key      /etc/dovecot/tls/server.key

RUN chown root:dovecot /etc/dovecot/users /etc/dovecot/master-users \
 && chmod 640 /etc/dovecot/users /etc/dovecot/master-users

EXPOSE 143
CMD ["dovecot", "-F"]
