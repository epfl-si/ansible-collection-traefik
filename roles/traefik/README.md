# `epfl_si.traefik.traefik` role

Run Træfik in Docker or Podman.


## Platform Requirements

- Python 3. Do yourself a favor and kick Python 2 out of your life today; it really is as simple as `ansible_python_interpreter: python3` in your inventory
- yum or apt package manager
- Properly configured to live in the 21st century — i.e. `yum install python-pip3` is expected to work with no `subscription-manager`-this or EPEL-that nonsense.

# Usage

Minimum configuration:

```
- name: Træfik
  hosts: all
  roles:
    - role: epfl_si.traefik.traefik
  vars:
    traefik_root_location: /srv/traefik
```

See `defaults/main.yml` for all the variables you can tweak.

# Tags

| Tag    | Purpose |
| -------- | ------- |
| `-t traefik`  | Run all tasks in the role (and nothing else from the rest of your playbook, presumably) |
| `-t traefik.config`  | Create or update configuration files only |
| `-t traefik.certificate`  | Create or update private key and certificate (self-signed by default; set `traefik_certificate_selfsigned` to `false` if you want a real certificate) |
| `-t traefik.docker`  | Set up image and container (Docker platform; the default) |
| `-t traefik.podman`  | Set up image and container for the Podman platform (requires setting `traefik_container_platform: podman`) |
