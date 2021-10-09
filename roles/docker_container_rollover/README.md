# `epfl_si.traefik.docker_container_rollover` Role

This role ensures that a docker container is set up according to a YAML spec (much like the “classical” `community.docker.docker_container` does); except that if the condition is not currently met, a zero-downtime rollover will be performed.

## Prerequisites

The `jq` and `docker-ps-traefik` commands must be installed on the target host. You can install the latter like this:

```
- name: "docker-ps-traefik script"
  pip:
    name: docker_ps_traefik
```

## Usage

When invoking the role, you must pass it a couple of variables. For instance:

```
- include_role:
    name: epfl_si.traefik.docker_container_rollover
    vars:
      # The container spec, as a dict that you could pass to  `community.docker.docker_container`
      container_spec:
        # You should put `{{ serial }}` somewhere in the container name, so that rollover
        # works properly. The `epfl_si.traefik.docker_container_rollover` role takes care
        # of setting the appropriate value for `serial`.
        name: "busybox-{{ serial }}"
        image: "busybox"
        labels:
          # Use Docker labels to tell Traefik what to do, for example:
          traefik.http.routers.busybox.rule: >-
            Host(`busybox.example.com`)
        # ... and more if needed (volumes, network, env etc.)
      # `unique_label` should be the name of a Docker label that this container
      # (and all its cousins) has, but no other containers on the same machine would
      # have. For example (to match the example labels, above):
      unique_label: "traefik.http.routers.busybox.rule"
      # `tag_to_force` is an optional Ansible tag, which will force a container rollover
      # is set. (Otherwise the rollover only happens if it is needed, i.e. the target
      # container is either missing or differs from the `container_spec`:)
      tag_to_force: "myapp.rollover.force"
```

💡 General Ansible tip (not related to `docker_container_rollover` in particular): if you want to guard the role with a tag (which is a distinct feature from what `tag_to_force` provides), be careful that `include_role` doesn't auto-tag the tasks within the role it invokes. This means that you need a construct like this, otherwise the tasks within the role would never run:

```
- tags:
    - myapp.rollover
  include_role:
    name: epfl_si.traefik.docker_container_rollover
    apply:
      tags:
        - myapp.rollover
  vars:
    container_spec: ...  # See above
```
