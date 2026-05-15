import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code, validate_email_list
from cis.models.teacher import TeacherCourseCertificate
from cis.models.customuser import CustomUser

from cis.models.crontab import CronTab
from cis.models.settings import Setting


# Single source of truth for which shortcodes the MOU text supports.
# Read by both the SettingForm field below (for the admin UI) and by
# MOUSignature.mou_text (for runtime gating). The 'role_lookup' choice covers
# the entire {{role_<attr>_<Position>}} family (any attr, any position).
AVAILABLE_SHORTCODES = [
    ('signature_1',             '{{signature_1}} — Signature box (weight 1)'),
    ('signature_2',             '{{signature_2}} — Signature box (weight 2)'),
    ('signature_3',             '{{signature_3}} — Signature box (weight 3)'),
    ('signature_4',             '{{signature_4}} — Signature box (weight 4)'),
    ('highschool_name',         '{{highschool_name}} — High school name'),
    ('highschool_ceeb',         '{{highschool_ceeb}} — High school CEEB code'),
    ('highschool_address1',     '{{highschool_address1}} — High school street address'),
    ('highschool_city',         '{{highschool_city}} — High school city'),
    ('highschool_state',        '{{highschool_state}} — High school state'),
    ('highschool_zip',          '{{highschool_zip}} — High school ZIP / postal code'),
    ('academic_year',           '{{academic_year}} — Academic year'),
    ('teacher_list',            '{{teacher_list}} — Certified teachers list'),
    ('choice_teacher_list',     '{{choice_teacher_list}} — Choice (CCCL) teachers list'),
    ('pathways_teacher_list',   '{{pathways_teacher_list}} — Pathways teachers list'),
    ('pathways_course_list',    '{{pathways_course_list}} — Pathways courses list'),
    ('choice_course_list',      '{{choice_course_list}} — Choice (CCCL) courses list'),
    ('facilitator_course_list', '{{facilitator_course_list}} — Facilitator courses list'),
    ('future_course_list',      '{{future_course_list}} — Submitted future courses list'),
    ('role_lookup',             '{{role_<attr>_<Position>}} — Per-position admin lookup (any attribute, any position)'),
]


class SettingForm(forms.Form):

    teacher_course_status = forms.MultipleChoiceField(
        choices=TeacherCourseCertificate.STATUS_OPTIONS,
        label='Teacher Course Cert Status',
        help_text='These status(es) will be included in the teacher_list short code.',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'col-md-4 col-sm-12'})
    )

    available_shortcodes = forms.MultipleChoiceField(
        choices=AVAILABLE_SHORTCODES,
        label='Available Shortcodes',
        help_text=(
            'Shortcodes selected here are substituted in MOU text at render time. '
            'Unselected shortcodes are replaced with an empty string. Leave all '
            'selected to keep current behavior.'
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'col-md-12'}),
    )

    custom_css = forms.CharField(
        max_length=None,
        widget=forms.Textarea(attrs={'rows': 12, 'class': 'col-md-12', 'style': 'font-family: monospace;'}),
        required=False,
        help_text=(
            'Optional CSS injected into the MOU document template (used for both '
            'on-screen rendering and the generated PDF). Do not include the '
            '<code>&lt;style&gt;</code> tags &mdash; just the CSS rules. Example: '
            '<code>body { font-family: Georgia, serif; } h1 { color: #003366; }</code>'
        ),
        label='Custom MOU CSS',
    )

    future_course_list_template = forms.CharField(
        max_length=None,
        widget=forms.Textarea(attrs={'rows': 12, 'class': 'col-md-12'}),
        validators=[validate_html_short_code],
        required=False,
        help_text=mark_safe(
            'Django-template HTML used by the <code>{{future_course_list}}</code> shortcode. '
            'Leave blank to fall back to the bundled '
            '<code>mou/templates/future_section_courses.html</code>.'
            '<br><br>'
            '<strong>Context:</strong> <code>courses</code> is a queryset of <code>FutureCourse</code> '
            'records for this MOU\'s highschool + academic year (only those with '
            '<code>submitted_on</code> set).'
            '<br><br>'
            '<strong>Per-record fields</strong> (use inside <code>{% for record in courses %}</code>):'
            '<ul class="mb-1">'
            '<li><code>{{ record.teacher_course.course.title }}</code> &mdash; course title</li>'
            '<li><code>{{ record.teacher_course.course.name }}</code> &mdash; course code/name</li>'
            '<li><code>{{ record.teacher_course.teacher_highschool.teacher.user.first_name }}</code> / '
            '<code>...last_name</code> &mdash; instructor name</li>'
            '<li><code>{{ record.teacher_course.status }}</code> &mdash; certification status</li>'
            '<li><code>{{ record.academic_year }}</code> &mdash; academic year</li>'
            '<li><code>{{ record.teaching_or_not }}</code> &mdash; "Yes" / "No"</li>'
            '<li><code>{{ record.section_display_html }}</code> &mdash; pre-formatted section '
            'lines joined with <code>&lt;br&gt;</code> and marked safe, rendered through the '
            'future_sections <code>display_template</code> configured at '
            '<code>/ce/future_sections/</code>. Drop in directly &mdash; no iteration or '
            '<code>|safe</code> needed. Use the list form '
            '<code>{{ record.section_display }}</code> + '
            '<code>{% for line in record.section_display %}{{ line }}<br>{% endfor %}</code> '
            'if you need per-line markup.</li>'
            '<li><code>{{ record.section_info.sections }}</code> &mdash; raw list of section dicts '
            'if you want field-level access</li>'
            '</ul>'
            '<strong>Section dict fields</strong> (inside <code>{% for section in record.section_info.sections %}</code>): '
            '<code>term_name</code>, <code>estimated_enrollment</code>, <code>class_period</code>, '
            '<code>instruction_mode</code>, <code>highschool_course_name</code>, '
            '<code>number_of_sections</code>, <code>full_year</code>, <code>trimester</code>, '
            '<code>fall_only</code>, <code>spring_only</code>, <code>notes</code>, '
            '<code>teacher_changed</code>, <code>file</code> (uploaded syllabus URL).'
            '<br><br>'
            '<strong>Tip:</strong> prefer <code>record.section_display</code> &mdash; admins control its '
            'format from the future_sections settings page, so the MOU stays in sync without editing '
            'this template.'
        ),
        label='{{future_course_list}} HTML Template',
    )

    college_administrator_1 = forms.ModelChoiceField(
        queryset=None,
        label='College Administrator 1',
        required=False,
        help_text='This user will be added with a weight of 3 and will be notified',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))
    
    college_administrator_2 = forms.ModelChoiceField(
        queryset=None,
        label='College Administrator 2',
        required=False,
        help_text='This user will be added with a weight of 4 and will be notified',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No'),
        ('Debug', 'Debug')
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Enabled',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    notify_address = forms.CharField(
        help_text='Comma separated list of (staff/testers) email addresses for debug mode, and also for notifying when roster status is changed',
        label="Notification List",
        validators=[validate_email_list]
    )
    email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Pending Signature Email Subject")

    email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Supports HTML. Customize the message with {{highschool_name}}, {{role}},{{signator_firstname}}, {{signature_lastname}}, {{mou_title}}, {{signature_url}}. <a href="#" class="float-right" onClick="do_bulk_action(\'mou.email_settings\', \'email_message\')" >See Preview</a>',
        label="Pending Signature Email")

    signed_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Signature Received - Email Subject")

    signed_email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Supports HTML. Customize the message with {{highschool_name}}, {{role}},{{signator_firstname}}, {{signature_lastname}}, {{mou_title}}, {{mou_download_link}}. <a href="#" class="float-right" onClick="do_bulk_action(\'mou.email_settings\', \'signed_email_message\')" >See Preview</a>',
        label="Signature Received - Email")

    change_request_email_subject = forms.CharField(
        max_length=200,
        required=False,
        help_text='',
        label="Change Request - Email Subject")

    change_request_email_message = forms.CharField(
        max_length=None,
        required=False,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Supports HTML. Sent to the MOU Manager (or the Notification List if no manager is assigned) when a signer requests changes. Customize with {{highschool_name}}, {{signator_firstname}}, {{signator_lastname}}, {{mou_title}}, {{comment}}, {{mou_url}}, {{signature_url}}. <a href="#" class="float-right" onClick="do_bulk_action(\'mou.email_settings\', \'change_request_email_message\')" >See Preview</a>',
        label="Change Request - Email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        staff = CustomUser.objects.filter(
            is_active=True,
            is_staff=True,
        ).order_by('last_name')

        self.fields['college_administrator_1'].queryset = staff
        self.fields['college_administrator_2'].queryset = staff

    def clean_college_administrator_1(self):
        if self.cleaned_data.get('college_administrator_1'):
            return self.cleaned_data.get('college_administrator_1').id
        return None
    
    def clean_college_administrator_2(self):
        if self.cleaned_data.get('college_administrator_2'):
            return self.cleaned_data.get('college_administrator_2').id
        return None
    
    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value
        
        return result


class email_settings(SettingForm):
    key = str(__name__)

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def preview(self, request, field_name):

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        email_settings = self.from_db()

        if field_name == 'email_message':
            email = email_settings.get('email_message')
            subject = email_settings.get('email_subject')

        elif field_name == 'signed_email_message':
            email = email_settings.get('signed_email_message')
            subject = email_settings.get('signed_email_subject')

        elif field_name == 'change_request_email_message':
            email = email_settings.get('change_request_email_message')
            subject = email_settings.get('change_request_email_subject')

        email_template = Template(email)
        context = Context({
            'signator_firstname': request.user.first_name,
            'signator_lastname': request.user.last_name,
            'highschool_name': "HS 1",
            'mou_title': "MOU Title",
            'role': "Role",
            'signature_url': "https://someurl.com",
            'mou_download_link': 'https://downloadurl.com',
            'comment': 'Example comment from the signer about MOU language.',
            'mou_url': 'https://someurl.com/ce/highschools/mous/mou/<uuid>',
        })

        text_body = email_template.render(context)
        
        return render(
            request,
            'cis/email.html',
            {
                'message': text_body
            }
        )

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        defaults = {
            'is_active': "Debug",
            'available_shortcodes': [k for k, _ in AVAILABLE_SHORTCODES],
            'change_request_email_subject': 'MOU Change Request — {{highschool_name}}',
            'change_request_email_message': (
                '<p>{{signator_firstname}} {{signator_lastname}} from '
                '{{highschool_name}} has requested changes to <strong>{{mou_title}}</strong>.</p>'
                '<p><strong>Comment:</strong></p>'
                '<blockquote>{{comment}}</blockquote>'
                '<p><a href="{{mou_url}}">Open MOU</a> &middot; '
                '<a href="{{signature_url}}">Signer link</a></p>'
            ),
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = self._to_python()
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
