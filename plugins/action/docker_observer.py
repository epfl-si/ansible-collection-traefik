#!/usr/bin/env python3

"""
Subscribe to the Docker and/or Træfik state and react with a script.

Invoking a `docker_observer` task causes a Docker container to be built and
spun up on the target host (much like if you had invoked `docker_image` and
`docker_container` directly). That container gets access to the Docker socket
(/var/run/docker.sock) and runs a small Python script (using
https://pypi.org/project/aiodocker/) that calls back into your code every time
the set of Docker container changes.
"""

EXAMPLES = r"""
- name: Update Prometheus file-based service discovery
  epfl_si.traefik.docker_observer:
    name: some-cool-name  # Mandatory; will be used for both the image and the container
    volumes:
      - /srv/traefik/dynamic:/traefik/dynamic
    python_dependencies:
      - pyyaml
      - atomicwrites
    python_script: |
      import yaml
      from atomicwrites import atomic_write

      @on_docker_containers_changed
      async def write_prometheus_static_discovery_file(docker_containers):
          for container in containers:
              details = await container.show()
              ...

"""

from ansible.plugins.action import ActionBase
from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import Subaction

class DockerObserverAction(ActionBase):
    def run (self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        a = Subaction(caller=self, task_vars=task_vars)

        args = self._task.args

        python_script = args['python_script']
        if "docker_observer_lib" not in python_script:
            python_script = (
                "import os, sys; sys.path.append(os.path.dirname(os.path.realpath(__file__)))\n" +
                "from docker_observer_lib import *\n" +
                python_script +
                "\n\nrun_forever()\n")

        # Making and populating a scratch directory is considered a “query,” as
        # it has no impact on the state of the remote system (and also it must
        # always run, otherwise the next steps would not be able to reliably
        # distinguish green from yellow under --check)
        query_status = a.query("command",
                dict(_uses_shell=True,
                     _raw_params="""
set -e -x

workdir="$(mktemp --tmpdir -d docker_observer.XXXXXX)"

cd "$workdir"

(
  set -e -x; exec >&2   # Just being defensive

  cat > Dockerfile <<"H3RE_DOCKERFILE"
FROM python:slim
RUN pip3 install aiodocker aiofile %(userdeps)s
RUN mkdir /app
COPY *.py /app/
WORKDIR /app
CMD ["python3", "/app/main.py"]

H3RE_DOCKERFILE

  cat > docker_observer_lib.py <<"H3RE_DOCKER_OBSERVER_LIB"

import asyncio
from aiofile import async_open
import aiodocker
from inspect import iscoroutinefunction

__all__ = ('run_forever', 'on_docker_containers_changed')

class DockerWatcher:
    def __init__ (self, docker):
        self._docker = docker
        self._container_ids = []

    async def containers_changed (self):
        while True:
            l = await self._docker.containers.list()
            container_ids = [c.id for c in l]
            if self._container_ids != container_ids:
                self._container_ids = container_ids
                return l
            else:
                await asyncio.sleep(1)

callbacks=[]
def on_docker_containers_changed (f):
    callbacks.append(f)
    return f

async def observe_changes_forever ():
    watch = DockerWatcher(aiodocker.Docker())
    while True:
        containers = await watch.containers_changed()
        for callback in callbacks:
            if iscoroutinefunction(callback):
                await callback(containers)
            else:
                callback(containers)

def run_forever (loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()
        will_close_loop = True
    else:
        will_close_loop = False

    try:
        loop.run_until_complete(observe_changes_forever())
    finally:
        if will_close_loop:
            loop.close()

H3RE_DOCKER_OBSERVER_LIB

  cat > main.py <<"H3RE_MAIN_PY"
%(python_script)s
H3RE_MAIN_PY
)

/bin/pwd  # Only thing that should go to stdout
""" %
                     {
                         "userdeps": join(" ", args.get("python_dependencies", [])),
                         "python_script": python_script
                     }))
        workdir = query_status["stdout"]

        try:
            image_status = a.change(
                "docker_image",
                dict(
                    name=args["name"],
                    source="build",
                    force_source=True,
                    build=dict(path=workdir)),
                update_result=result)

            try:
                image_id = image_status["image"]["Id"]
            except KeyError:  # Will happen under --check
                image_id = args["name"]

            a.change(
                "docker_container",
                dict(
                    name=args["name"],
                    state="started",
                    image=image_id,
                    restart=bool(image_status["changed"]),
                    volumes=["/var/run/docker.sock:/var/run/docker.sock"] + args.get("volumes", []),
                    ports=args.get("ports"),
                    restart_policy=args.get("restart_policy", "unless-stopped")
                ),
                update_result=result)
        finally:
            if workdir:
                # See above re why rm -rf is a “query”
                a.query("command", dict(_raw_params="rm -rf %s" % workdir))

        return result


def join (separator, list_or_string):
    if not isinstance(list_or_string, list):
        list_or_string = [list_or_string]
    return separator.join(list_or_string)

ActionModule = DockerObserverAction
