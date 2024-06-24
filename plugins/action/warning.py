from ansible.plugins.action import ActionBase
from ansible.utils.display import Display

class ActionModule(ActionBase):
    module_spec = dict(
        argument_spec=dict(
            msg=dict(type='str')))

    def run(self, tmp=None, task_vars=None):
        Display().warning(self._task.args['msg'])
        return super(ActionModule, self).run(tmp, task_vars)
