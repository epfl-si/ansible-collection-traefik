#!/usr/bin/env python
# -*- coding: utf-8; -*-
# Tested with Python 2.7.2 and Python 3.6

"""%(0)s - Query Traefik to figure out the state of Docker backends

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

__version__ = "0.1.1"

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
        return self.state[u'Config'][u'Entrypoint'] + self.state[u'Config'][u'Cmd']

    @property
    def status(self):
        return self.state[u'State'][u'Status']

    def has_label(self, key_or_keyvalue, value=None):
        if value is None:
            key, value = re.match('^(.*?)=(.*)$', key_or_keyvalue).groups()
        else:
            key = key_or_keyvalue

        for k, v in self.state[u'Config'][u'Labels'].items():
            if u(k) == u(key) and u(v) == u(value):
                return True
        return False

    def __repr__(self):
        return '<%s id=%s "%s">' % (self.__class__.__name__, self.id, self.name)

class DockerNetwork:
    def __init__(self, name, docker_inspect_struct):
        self.name = name
        self._details = docker_inspect_struct

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.name)

class TraefikConfigurationError(Exception):
    def __init__(self, uri):
        super(TraefikConfigurationError, self).__init__("""Traefik is not configured to serve at %s.

Please enable both API and Prometheus metrics serving:

- pass --api command-line flag when starting Traefik
- (for Traefik version 1.7) In traefik.toml, add an empty section that goes like

  [metrics]
    [metrics.prometheus]

""" % uri)

class Traefik:
    def __init__(self, opts):
        self.container = DockerContainer(opts.traefik_container_name)

    @property
    def network(self):
        return self.container.network

    def _api_state(self):
        (api, _) = self._api_infos
        return json.loads(api)

    def _prometheus_state(self):
        (_, prometheus) = self._api_infos
        state = []
        for line in prometheus.split("\n"):
            matched = re.match('^traefik_backend_server_up{backend="(.*)",url="(.*)"} ([01])',
                               line)
            if not matched:
                continue

            (backend, url, health) = matched.groups()
            state.append({'backend': backend, 'url': url, 'health': int(health)})

        return state

    @cached_property
    def _api_infos(self):
        traefik_hostname_in_docker = '%s.%s' % (self.container.name, self.network.name)
        traefik_api_url_prefix = 'http://%s:8080' % (traefik_hostname_in_docker)
        cmd = Command(['docker', 'run', '--rm',
                        '--network', self.network.name,
                        'busybox', 'sh', '-c', """
echo "===== TRAEFIK API ====="
wget -q -O- %s/api/providers/docker 2>&1 || true
echo "===== PROMETHEUS ====="
wget -q -O- %s/metrics 2>&1 || true
""" % (traefik_api_url_prefix, traefik_api_url_prefix)])

        matched = re.match('===== TRAEFIK API =====\n(.*)===== PROMETHEUS =====(.*)$',
                           u(cmd.stdout), re.DOTALL)
        if not matched:
            raise ValueError(u(cmd.stdout))

        (traefik_api, prometheus) = matched.groups()
        if self._wget_response_is_404(traefik_api):
            raise TraefikConfigurationError('/api/providers/docker')
        if self._wget_response_is_404(prometheus):
            raise TraefikConfigurationError('/metrics')
        return (traefik_api, prometheus)

    def _wget_response_is_404(self, wget_response):
        return "404 not found" in wget_response.lower()

    def find_backend_info(self, container):
        ip = container.ip_in_network(self.network)
        if ip is None:
            return None

        for backend in self.BackendInfo.all(self):
            if str(ip) in backend.ips:
                return backend

    class BackendInfo:
        def __init__(self, traefik, name):
            self.name = name
            self._traefik_api_info = traefik._api_state()[u'backends'][u(name)]
            self._prometheus_info = None
            for prometheus_info in traefik._prometheus_state():
                if str(prometheus_info['backend']) == str(name):
                    self._prometheus_info = prometheus_info
                    break

        @classmethod
        def all(cls, traefik):
            if not hasattr(cls, '_all'):
                cls._all = [cls(traefik, name)
                            for name in traefik._api_state()[u'backends'].keys()]
            return cls._all

        @cached_property
        def ips(self):
            ips = []
            for server_info in self._traefik_api_info['servers'].values():
                url = server_info[u'url']
                matched = re.match('^http://([0-9.]+)(?:[:/]|$)', url)
                if matched:
                    ips.append(matched.group(1))
            return ips

        @property
        def healthy(self):
            return self._prometheus_info['health'] == 1

        def __repr__(self):
            return '<%s %s ip=%s health=%s>' % (
                self.__class__.__name__, self.name,
                self.ip, self._prometheus_info[u'health'])


def render_table_ala_docker_ps(traefik, containers):
    header = "CONTAINER ID        IMAGE                   COMMAND                  STATUS         HEALTHY  NAME"
    print(header)

    columns = [0 if padding is None else len(title) + len(padding)
               for title, padding in pairwise(re.split('(  +)', header) + [None])]

    for c in containers:
        bi = traefik.find_backend_info(c)
        display_line = ""
        for width, value in zip(
                columns,
                [c.id,
                 c.image,
                 ' '.join(c.command),
                 c.status,
                 u'✓' if bi.healthy else u'✗',
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

def main(opts=None):
    if opts is None:
        opts = Options()
    traefik = Traefik(opts)

    def show_this_container(opts, traefik, d):
        bi = traefik.find_backend_info(d)
        if not bi:
            return False
        if opts.filter_unhealthy and not bi.healthy:
            return False
        if len(opts.label_filters):
            for l in opts.label_filters:
                if d.has_label(l):
                    return True
            return False
        return True

    containers_to_show = [d for d in DockerContainer.all()
                          if show_this_container(opts, traefik, d)]
    if opts.terse_output:
        for d in containers_to_show:
            print(d.id)
    else:
        render_table_ala_docker_ps(traefik, containers_to_show)


if __name__ == '__main__':
    main()
