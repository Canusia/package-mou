from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mou', '0004_mousignator_college_user_and_title'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mousignature',
            name='status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Not Ready To Sign'),
                    ('next', 'Next Up'),
                    ('pending', 'Pending Signature'),
                    ('changes_requested', 'Changes Requested'),
                    ('signed', 'Signed'),
                ],
                max_length=20,
                null=True,
                verbose_name='Status',
            ),
        ),
    ]
