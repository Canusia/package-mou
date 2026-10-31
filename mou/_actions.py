"""Vendored copy of myce.component_registry.ActionRegistry (package-mou#2).

Used by mou.actions only on hosts without myce.component_registry. Keep it in
step with the original; the behaviour must be identical.
"""
from collections import OrderedDict
from importlib import import_module

from django.http import JsonResponse


class ActionRegistry:
    def __init__(self, action_groups=None):
        self._groups = action_groups if action_groups is not None else OrderedDict()

    def action(self, group, label, scope, slug=None, method='ajax',
               icon=None, btn_class=None, confirm=None, permission=None):
        """Decorator that registers the decorated function as an action."""
        def decorator(fn):
            action_slug = slug or fn.__name__
            if group not in self._groups:
                self._groups[group] = {'actions': OrderedDict()}
            self._groups[group]['actions'][action_slug] = {
                'handler': fn,
                'label': label,
                'scope': scope,
                'method': method,
                'icon': icon,
                'btn_class': btn_class,
                'confirm': confirm,
                'permission': permission,
            }
            return fn
        return decorator

    def _resolve_handler(self, dotted_path):
        module_path, func_name = dotted_path.rsplit('.', 1)
        module = import_module(module_path)
        return getattr(module, func_name)

    def _find_action(self, slug):
        for group in self._groups.values():
            actions = group.get('actions', {})
            if slug in actions:
                return actions[slug]
        return None

    def dispatch(self, request, action_slug):
        action = self._find_action(action_slug)
        if action is None:
            return JsonResponse({
                'outcome': 'alert',
                'status': 'error',
                'title': 'Error',
                'message': 'Invalid action.',
            }, status=400)

        permission = action.get('permission')
        if permission is not None and not permission(request.user):
            return JsonResponse({
                'outcome': 'alert',
                'status': 'error',
                'title': 'Permission Denied',
                'message': 'You do not have permission to perform this action.',
            }, status=403)

        handler = action.get('handler')
        if handler is None:
            return JsonResponse({
                'outcome': 'alert',
                'status': 'error',
                'title': 'Error',
                'message': 'Invalid action.',
            }, status=400)

        if callable(handler):
            return handler(request)
        return self._resolve_handler(handler)(request)

    def for_scope(self, scope, user=None):
        filtered = OrderedDict()
        for group_key, group in self._groups.items():
            filtered_actions = OrderedDict()
            for slug, action in group.get('actions', {}).items():
                if scope not in action.get('scope', []):
                    continue
                permission = action.get('permission')
                if permission is not None and user is not None and not permission(user):
                    continue
                filtered_actions[slug] = action
            if filtered_actions:
                filtered[group_key] = {'actions': filtered_actions}
        return filtered
