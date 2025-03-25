# Generated by Django 4.2 on 2025-03-24 16:32

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        # ('cis', '0019_alter_classsection_co_reqs_alter_customuser_email_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='MOU',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=100)),
                ('created_on', models.DateTimeField(auto_now_add=True, verbose_name='Created On')),
                ('group_by', models.CharField(choices=[('highschool', 'School')], default='highschool', max_length=50)),
                ('send_on_after', models.DateTimeField(blank=True, null=True)),
                ('send_until', models.DateTimeField(blank=True, null=True)),
                ('cron', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True, null=True)),
                ('mou_text', models.TextField(blank=True, null=True)),
                ('status', models.CharField(blank=True, choices=[('draft', 'Draft'), ('ready', 'Ready to Send')], default='draft', max_length=10, null=True, verbose_name='Status')),
                ('meta', models.JSONField(blank=True, default=dict, null=True)),
                ('academic_year', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='cis.academicyear', verbose_name='Academic Year')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
            ],
            options={
                'ordering': ['-academic_year', 'title'],
            },
        ),
        migrations.CreateModel(
            name='MOUSignator',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_on', models.DateTimeField(auto_now_add=True, verbose_name='Created On')),
                ('weight', models.SmallIntegerField(default=1, verbose_name='Weight')),
                ('role_type', models.CharField(choices=[('highschool_admin', 'School Administrator'), ('district_admin', 'District Administrator')], default='highschool_admin', max_length=100, verbose_name='Role Type')),
                ('role', models.UUIDField(verbose_name='Role')),
                ('meta', models.JSONField(blank=True, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Created By')),
                ('mou', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='mou.mou', verbose_name='Created By')),
            ],
        ),
        migrations.CreateModel(
            name='MOUNote',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('note', models.TextField()),
                ('createdon', models.DateTimeField(auto_now=True)),
                ('parent', models.UUIDField(blank=True, null=True)),
                ('meta', models.JSONField(blank=True, null=True)),
                ('createdby', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('meo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='mou.mou')),
            ],
            options={
                'ordering': ['createdon'],
            },
        ),
        migrations.CreateModel(
            name='MOUSignature',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_on', models.DateTimeField(auto_now_add=True, verbose_name='Created On')),
                ('status', models.CharField(blank=True, choices=[('', 'Not Ready To Sign'), ('pending', 'Pending Signature'), ('signed', 'Signed')], max_length=10, null=True, verbose_name='Status')),
                ('meta', models.JSONField(blank=True, default=dict, null=True)),
                ('highschool', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='cis.highschool', verbose_name='School')),
                ('signator', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Signator')),
                ('signator_template', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='mou.mousignator', verbose_name='Signator Templates')),
            ],
            options={
                'unique_together': {('highschool', 'signator', 'signator_template')},
            },
        ),
    ]
