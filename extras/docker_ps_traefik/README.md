# docker-ps-traefik

`docker-ps-traefik` is a standalone script with no Python dependencies
besides what is found in the standard distribution.

It works like `docker ps`, except there is an additional column to
indicate container health (from Traefik's point of view).

[traefik](https://traefik.io/) must be configured for [docker
integration](https://docs.traefik.io/providers/docker/), and it must
have both API (`--api`) and Prometheus turned on in its configuration.

Uses of this script:
- as a systems administration tool
- as a helper to facilitate zero-downtime rollover
