# Versions

## Version 0.6.0

- Add variable to enable metrics for internal resources (`traefik_metrics_add_internals`)

## Version 0.5.0

- Support for Let's Encrypt a.k.a. ACME
  - Set up one (or more) of your routers as per https://doc.traefik.io/traefik/routing/routers/#certresolver
  - Once this works (but not before!) set `traefik_use_acme_prod_ca` to `true`

## Version 0.4.0

- Support for Podman
- `epfl_si.traefik.dynamic_config` action plugin

# Versions 0.3.x

## Version 0.3.0

- New `epfl_si.traefik.docker_container_rollover` role

# Versions 0.2.x

## Version 0.2.0

Minor un-feature version

- Remove `docker_collection` module; now lives in the [epfl_si.docker](https://galaxy.ansible.com/epfl_si/docker) Ansible collection instead
