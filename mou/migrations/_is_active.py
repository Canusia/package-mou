"""Shared helpers for the ``is_active`` upgrade migration (0006).

Kept in a plain module (rather than inline in the migration) so both the
migration itself and the test suite can import ``_is_active_keys`` /
``_set_live`` without dealing with the leading-digit module name.
"""


def _is_active_keys():
    """Both settings-key spellings this package can be installed under.

    ``email_settings.key`` is ``str(__name__)``, which is ``mou.settings.…``
    when pip-installed flat and ``mou.mou.settings.…`` as an in-tree
    submodule.
    """
    return (
        'mou.settings.email_settings',
        'mou.mou.settings.email_settings',
    )


def _set_live(setting_model):
    for key in _is_active_keys():
        for setting in setting_model.objects.filter(key=key):
            value = dict(setting.value or {})
            value['is_active'] = 'Yes'
            setting.value = value
            setting.save(update_fields=['value'])
