from collections import OrderedDict

from myce.component_registry import ActionRegistry

# Groups are pre-declared to control dropdown order. Handlers register
# themselves via @mou_actions.action(...) decorators in mou/views.py.
mou_actions = ActionRegistry(OrderedDict({
    'general': {'actions': OrderedDict()},
    'danger': {'actions': OrderedDict()},
}))
