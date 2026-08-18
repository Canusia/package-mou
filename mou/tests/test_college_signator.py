import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from cis.models.term import AcademicYear


def _models():
    try:
        from mou.mou.models import MOU, MOUSignator
        from mou.mou.forms import MOUSignatorForm
        from mou.mou.settings.helpers import get_max_signator_weight
    except ImportError:
        from mou.models import MOU, MOUSignator
        from mou.forms import MOUSignatorForm
        from mou.settings.helpers import get_max_signator_weight
    return MOU, MOUSignator, MOUSignatorForm, get_max_signator_weight


class CollegeSignatorTests(TestCase):
    def setUp(self):
        MOU, MOUSignator, _, _ = _models()
        User = get_user_model()
        self.user = User.objects.create_user(
            username='ce@example.com', email='ce@example.com',
            password='x', is_staff=True,
        )
        self.vp = User.objects.create_user(
            username='vp@example.com', email='vp@example.com',
            password='x', is_staff=True, first_name='Val', last_name='Provost',
        )
        self.ay = AcademicYear.objects.create(name='2026-27')
        self.mou = MOU.objects.create(
            title='AY MOU', cron='0 7 * * *', group_by='highschool',
            academic_year=self.ay, created_by=self.user,
        )

    def test_sexy_role_uses_college_title(self):
        MOU, MOUSignator, _, _ = _models()
        sig = MOUSignator.objects.create(
            mou=self.mou, weight=1, role_type='college_admin',
            role=uuid.uuid4(), created_by=self.user,
            college_user=self.vp,
            title='Vice President for Academic Affairs',
        )
        self.assertEqual(sig.sexy_role, 'Vice President for Academic Affairs')

    def test_duplicate_copies_college_user_and_title(self):
        MOU, MOUSignator, _, _ = _models()
        MOUSignator.objects.create(
            mou=self.mou, weight=1, role_type='college_admin',
            role=uuid.uuid4(), created_by=self.user,
            college_user=self.vp,
            title='Director of College and HS Partnerships',
        )
        dup = self.mou.duplicate(self.user)
        cloned = MOUSignator.objects.get(mou=dup, weight=1)
        self.assertEqual(cloned.college_user_id, self.vp.id)
        self.assertEqual(cloned.title, 'Director of College and HS Partnerships')

    def test_weight_choices_follow_max_signator_weight(self):
        from cis.models.settings import Setting
        _, _, MOUSignatorForm, get_max_signator_weight = _models()
        Setting.objects.update_or_create(
            key='mou.mou.settings.email_settings',
            defaults={'value': {'max_signator_weight': 6, 'allow_college_admin_any_weight': 'Yes'}},
        )
        # Also write the non-nested key used when the app is installed as `mou`.
        Setting.objects.update_or_create(
            key='mou.settings.email_settings',
            defaults={'value': {'max_signator_weight': 6, 'allow_college_admin_any_weight': 'Yes'}},
        )
        self.assertEqual(get_max_signator_weight(), 6)
        form = MOUSignatorForm(record=None, mou_id=self.mou.id)
        weights = [c[0] for c in form.fields['weight'].choices if c[0] != '']
        self.assertEqual(weights, [1, 2, 3, 4, 5, 6])

    def test_college_admin_may_be_weight_1(self):
        _, _, MOUSignatorForm, _ = _models()
        from cis.models.settings import Setting
        Setting.objects.update_or_create(
            key='mou.mou.settings.email_settings',
            defaults={'value': {'max_signator_weight': 8, 'allow_college_admin_any_weight': 'Yes'}},
        )
        Setting.objects.update_or_create(
            key='mou.settings.email_settings',
            defaults={'value': {'max_signator_weight': 8, 'allow_college_admin_any_weight': 'Yes'}},
        )
        form = MOUSignatorForm(
            record=None,
            mou_id=self.mou.id,
            data={
                'mou_id': str(self.mou.id),
                'action': 'edit_mou_signator',
                'id': '-1',
                'role_type': 'college_admin',
                'college_user': self.vp.id,
                'college_title': 'Director of College and HS Partnerships',
                'weight': '1',
                'complete_extra_form': '2',
            },
        )
        self.assertTrue(form.is_valid(), msg=form.errors)
        saved = form.save(type('R', (), {'user': self.user})(), self.mou)
        self.assertEqual(int(saved.weight), 1)
        self.assertEqual(saved.college_user_id, self.vp.id)
        self.assertEqual(saved.title, 'Director of College and HS Partnerships')
