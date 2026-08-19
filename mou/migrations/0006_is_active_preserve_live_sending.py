"""Existing installs keep sending live email after is_active becomes the switch.

``is_active`` was decorative before this release: nothing read it, and
install() seeded it to "Debug". Its stored value therefore carries no
intent, and the change that PRESERVES prior behaviour is to set every
existing row to "Yes". New installs still default to "Debug" via install().
"""
from django.db import migrations

from ._is_active import _set_live


def forward(apps, schema_editor):
    _set_live(apps.get_model('cis', 'Setting'))


def backward(apps, schema_editor):
    """Deliberately a no-op: we cannot recover a value that never had meaning."""


class Migration(migrations.Migration):

    dependencies = [
        ('mou', '0005_mousignature_next_up_status'),
        ('cis', '__first__'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
