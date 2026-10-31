from collections import OrderedDict

from .compat import HAS_COMPONENT_REGISTRY

# Hosts without myce.component_registry get the vendored copy (package-mou#2).
if HAS_COMPONENT_REGISTRY:
    from myce.component_registry import ActionRegistry
else:
    from ._actions import ActionRegistry

# Groups are pre-declared to control dropdown order. Handlers register
# themselves via @mou_actions.action(...) decorators in mou/views.py.
mou_actions = ActionRegistry(OrderedDict({
    'general': {'actions': OrderedDict()},
    'danger': {'actions': OrderedDict()},
}))
