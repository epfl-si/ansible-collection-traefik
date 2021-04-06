#!/usr/bin/env python
# -*- coding: utf-8; -*-
# Tested with Python 2.7.2 and Python 3.6

"""%(0)s - Query Traefik to figure out the state of Docker services

Works more or less like `docker ps', but cross-references the Traefik
state. Specifically,

* only front-end containers (i.e. known to Traefik) are displayed

* optionally, containers that are unhealthy from the point of view of
  Traefik are skipped

The order is kept the same as `docker ps` output, i.e. most recent containers
come first

Usage: %(0)s [options]

Options:
    -t|--traefik-container-name <traefik_container_name>
         The name or Docker ID of the Traefik container to interrogate

    -l|--label <foo>=<bar>
         Only show containers that match this label

    --healthy
         Only show healthy containers (according to Traefik)

    -q
         Show only Docker IDs (like `docker ps -q').
"""

__version__ = "0.2.1"

import getopt
import itertools
import json
import re
import subprocess
import sys

def usage():
    print(__doc__ % { '0': sys.argv[0]})
    sys.exit(2)

class Options:
    def __init__(self, argv=sys.argv[1:]):
        try:
            shortopts, longopts = getopt.getopt(
                argv,
                't:l:q',
                ['traefik-container-name=', 'label=', 'healthy'])
        except getopt.GetoptError:
            usage()

        self.traefik_container_name = 'traefik'
        self.label_filters = []
        self.filter_unhealthy = False
        self.terse_output = False
        for (k, v) in shortopts + longopts:
            if k in ('-t', '--traefik-container-name'):
                self.traefik_container_name = v
            elif k in ('-l', '--label'):
                self.label_filters.append(v)
            elif k in ('--healthy'):
                self.filter_unhealthy = True
            elif k in ('-q'):
                self.terse_output = True

def u(str):
    try:
        return unicode(str)
    except NameError:  # Python 3
        try:
            return str.decode('utf-8')
        except AttributeError:
            return str

class cached_property(object):
    """
    A property that is only computed once per instance and then replaces itself
    with an ordinary attribute. Deleting the attribute resets the property.
    Source: https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76
    """  # noqa

    def __init__(self, func):
        self.__doc__ = getattr(func, "__doc__")
        self.func = func

    def __get__(self, obj, cls):
        if obj is None:
            return self

        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value

class Command:
    def __init__(self, argv):
        process = subprocess.Popen(argv, shell=False, stdout=subprocess.PIPE)
        (self.stdout, _) = process.communicate()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, argv)

    @cached_property
    def stdout_lines(self):
        return u(self.stdout).split(u'\n')

    @cached_property
    def json(self):
        return json.loads(self.stdout)

class DockerContainer:
    def __init__(self, id):
        self._id = id

    @cached_property
    def state(self):
        return Command(['docker', 'inspect', self._id]).json[0]

    @classmethod
    def all(cls):
        if not hasattr(cls, '_all'):
            cls._all = [cls(id)
                        for id in Command(['docker', 'ps', '-q']).stdout_lines
                        if id]
        return cls._all

    def networks(self):
        for k, v in self.state[u"NetworkSettings"][u"Networks"].items():
            yield (k, DockerNetwork(k, v))

    @property
    def network(self):
        for k, v in self.networks():
            return v

    def ip_in_network(self, network):
        for k, v in self.state[u"NetworkSettings"][u"Networks"].items():
            if str(k) == str(network.name):
                return str(v[u"IPAddress"])

    @cached_property
    def name(self):
        return re.match('^/?(.*)', self.state[u"Name"]).group(1)

    @property
    def id(self):
        return self.state[u"Id"][:12]

    @property
    def image(self):
        return u(self.state[u'Config'][u'Image'])

    @property
    def command(self):
        entrypoint = self.state[u'Config'][u'Entrypoint']
        cmd = self.state[u'Config'][u'Cmd']
        return (entrypoint or []) + (cmd or [])

    @property
    def status(self):
        return self.state[u'State'][u'Status']

    def has_label(self, key_or_keyvalue):
        matched = re.match('^(.*?)=(.*)$', key_or_keyvalue)
        if matched:
            key, value = matched.groups()
        else:
            key = key_or_keyvalue
            value = None

        for k, v in self.state[u'Config'][u'Labels'].items():
            if u(k) == u(key) and (value is None or u(v) == u(value)):
                return True
        return False

    def _traefik_service_labels(self):
        for k, v in self.state[u'Config'][u'Labels'].items():
            matched = re.match('^traefik\.(?P<protocol>http|tcp)\.services.(?P<name>\w+)\..*$', k)
            if matched:
                yield (matched, v)

    @property
    def traefik_service_name(self):
        names = set(matched['name'] for (matched, v) in self._traefik_service_labels())
        if len(names) > 2:
            return None    # Træfik is going to disregard this container
        elif len(names) == 1:
            return sole(names)
        else:
            name = self.name
            if name:
                return re.sub('_', '-', name)
            else:
                return name

    def __repr__(self):
        traefik_service_name = self.traefik_service_name
        return '<%s id=%s "%s" (service: %s)>' % (
            self.__class__.__name__, self.id,
            self.name,
            "None" if traefik_service_name is None else '"%s"' % traefik_service_name)

class DockerNetwork:
    def __init__(self, name, docker_inspect_struct):
        self.name = name
        self._details = docker_inspect_struct

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.name)

class TraefikConfigurationError(Exception):
    def __init__(self, uri):
        super(TraefikConfigurationError, self).__init__("""Traefik is not configured to serve at %s.

Please enable API serving in Træfik. For instructions refer to
https://doc.traefik.io/traefik/operations/api/#insecure

""" % uri)

class Traefik:
    def __init__(self, opts):
        self.container = DockerContainer(opts.traefik_container_name)

    @property
    def network(self):
        return self.container.network

    @cached_property
    def _api_services(self):
        traefik_hostname_in_docker = '%s.%s' % (self.container.name, self.network.name)
        traefik_api_url_prefix = 'http://%s:8080' % (traefik_hostname_in_docker)
        cmd = Command(['docker', 'run', '--rm',
                        '--network', self.network.name,
                        'busybox', 'sh', '-c', 
                       "wget -q -O- %s/api/http/services 2>&1 || true" %
                       traefik_api_url_prefix])
        traefik_api = u(cmd.stdout)

        if "404 not found" in traefik_api.lower():
            raise TraefikConfigurationError('/api/http/services')

        return json.loads(traefik_api)

    def get_container_state(self, container):
        api_service = sole(s for s in self._api_services
                           if s['name'] == "%s@docker" % container.traefik_service_name)
        if api_service is None:
            return None

        container_ip = container.ip_in_network(self.network)
        if not container_ip:
            return None

        class ContainerState(object):
            pass
        state = ContainerState()

        container_urls = set(
            v['url'] for v in api_service.get('loadBalancer', {}).get('servers', {})
            if 'url' in v and re.search(r'\b%s\b' % container_ip, v['url']))
        if not container_urls:
            # The Træfik service doesn't know about this container.
            # It might be incorrectly routed (e.g. wrong `traefik.docker.network`,
            # meaning we have been filtering by the wrong IP)
            state.healthy = False
        else:
            server_status = api_service.get('serverStatus', None)
            if server_status is None:
                # This service doesn't do health checks.
                state.healthy = True
            else:
                container_urls_up = set(k for k, v in server_status.items()
                                        if v == 'UP' and k in container_urls)
                state.healthy = len(container_urls_up) >= 1

        return state


def render_table_ala_docker_ps(traefik, containers):
    header = "CONTAINER ID        IMAGE                   COMMAND                  STATUS   HEALTHY  TRAEFIK SVC NAME     NAME"
    print(header)

    columns = [0 if padding is None else len(title) + len(padding)
               for title, padding in pairwise(re.split('(  +)', header) + [None])]

    for c in containers:
        state = traefik.get_container_state(c)
        display_line = ""
        for width, value in zip(
                columns,
                [c.id,
                 c.image,
                 ' '.join(c.command),
                 c.status,
                 u'✓' if state and state.healthy else u'✗' if state else u' ',
                 c.traefik_service_name,
                 c.name]):
            display_value = value
            if width > 0:
                if len(display_value) > width - 1:
                    display_value = display_value[:width - 2] + u'…'
                display_value = (u'{:<%d}' % width).format(display_value)
            display_line += display_value
        print(display_line)

def pairwise(iterable):
    "s -> (s0, s1), (s2, s3), (s4, s5), ..."
    # From https://stackoverflow.com/a/5389547/435004
    a = iter(iterable)
    if hasattr(itertools, 'izip'):  # Python 2.x
        return itertools.izip(a, a)
    else:                           # Python 3.x
        return zip(a, a)

def sole(l):
    l = list(l)
    if len(l) == 1:
        return l[0]
    else:
        return None

def main(opts=None):
    if opts is None:
        opts = Options()
    traefik = Traefik(opts)

    def show_this_container(opts, traefik, c):
        state = traefik.get_container_state(c)
        if opts.filter_unhealthy and not (state and state.healthy):
            return False
        if len(opts.label_filters):
            for l in opts.label_filters:
                if c.has_label(l):
                    return True
            return False
        return True

    containers_to_show = [c for c in DockerContainer.all()
                          if show_this_container(opts, traefik, c)]
    if opts.terse_output:
        for c in containers_to_show:
            print(c.id)
    else:
        render_table_ala_docker_ps(traefik, containers_to_show)


if __name__ == '__main__':
    main()
