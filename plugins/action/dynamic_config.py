from ansible.plugins.action import ActionBase
from ansible.template import Templar

from ansible_collections.epfl_si.actions.plugins.module_utils.subactions import Subaction
from ansible_collections.epfl_si.actions.plugins.module_utils.ansible_api import AnsibleActions

EXAMPLES = r'''
- name: "Some `routers` and `services` for Træfik
  epfl_si.traefik.dynamic_config:
    name: my-config
    content: |
      http:
        services:
          my-service:
            loadBalancer:
              servers:
              - url: http://localhost:8888
        routers:
          my-router:
            rule: Host("some.host.name")
            service: my-service
            tls: true
'''

class ActionModule(ActionBase):
    module_spec = dict(
        argument_spec=dict(
            name=dict(type='str'),
            content=dict(type='str')))

    @AnsibleActions.run_method
    def run (self, args, ansible_api):
        result = {}
        subaction = Subaction(ansible_api)
        subaction.result = result

        traefik_dir = ansible_api.expand_var(
            "{{ traefik_dynamic_config_dir }}",
            defaults=dict(traefik_dynamic_config_dir="{{ traefik_root_location }}/conf/dynamic"))

        subaction.change(
            "ansible.builtin.copy",
            dict(dest="%s/%s.yml" % (traefik_dir, args["name"]),
                 content=args["content"]))

        return result
