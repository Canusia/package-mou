import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from .helpers import DEFAULT_MAX_SIGNATOR_WEIGHT, DEFAULT_RETENTION_YEARS

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
# signature_N runs through DEFAULT_MAX_SIGNATOR_WEIGHT so a tenant can raise
# the chain length from settings without a code change; unused weights just
# render "Not yet signed".
def _signature_shortcodes(max_weight=DEFAULT_MAX_SIGNATOR_WEIGHT):
    return [
        (f'signature_{i}', f'{{{{signature_{i}}}}} — Signature for signer {i} in the order')
        for i in range(1, max_weight + 1)
    ]


AVAILABLE_SHORTCODES = _signature_shortcodes() + [
    ('highschool_name',         '{{highschool_name}} — High school name'),
    ('highschool_ceeb',         '{{highschool_ceeb}} — High school CEEB code'),
    ('highschool_address1',     '{{highschool_address1}} — High school street address'),
    ('highschool_city',         '{{highschool_city}} — High school city'),
    ('highschool_state',        '{{highschool_state}} — High school state'),
    ('highschool_zip',          '{{highschool_zip}} — High school ZIP / postal code'),
    ('district_name',           '{{district_name}} — District name'),
    ('district_address1',       '{{district_address1}} — District street address'),
    ('district_city',           '{{district_city}} — District city'),
    ('district_state',          '{{district_state}} — District state'),
    ('district_zip',            '{{district_zip}} — District ZIP / postal code'),
    ('academic_year',           '{{academic_year}} — Academic year'),
    ('teacher_list',            '{{teacher_list}} — Certified teachers list'),
    ('choice_teacher_list',     '{{choice_teacher_list}} — Choice (CCCL) teachers list'),
    ('pathways_teacher_list',   '{{pathways_teacher_list}} — Pathways teachers list'),
    ('pathways_course_list',    '{{pathways_course_list}} — Pathways courses list'),
    ('choice_course_list',      '{{choice_course_list}} — Choice (CCCL) courses list'),
    ('facilitator_course_list', '{{facilitator_course_list}} — Facilitator courses list'),
    ('future_course_list',      '{{future_course_list}} — Future courses list'),
    ('approved_course_list',    '{{approved_course_list}} — Approved / certified courses list'),
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
        help_text=(
            'Backup college signer if a college step does not have a person selected. '
            'Usually you can leave this blank and choose the person on each signer instead.'
        ),
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))
    
    college_administrator_2 = forms.ModelChoiceField(
        queryset=None,
        label='College Administrator 2',
        required=False,
        help_text=(
            'Second backup college signer if a college step does not have a person selected. '
            'Usually you can leave this blank and choose the person on each signer instead.'
        ),
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    max_signator_weight = forms.IntegerField(
        min_value=1,
        max_value=20,
        required=False,
        initial=DEFAULT_MAX_SIGNATOR_WEIGHT,
        label='Maximum number of signers',
        help_text=(
            'How many people can appear in the signing order. Raise this if you need '
            'more signatures on the agreement. Placeholders in the document are '
            '{{signature_1}}, {{signature_2}}, and so on.'
        ),
        widget=forms.NumberInput(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    allow_college_admin_any_weight = forms.ChoiceField(
        choices=[('Yes', 'Yes'), ('No', 'No')],
        required=False,
        initial='Yes',
        label='College staff can sign at any step',
        help_text=(
            'Yes lets college staff appear anywhere in the signing order '
            '(for example first, before the school). No limits college staff to '
            'steps 3 and 4 only.'
        ),
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    vacant_role_policy = forms.ChoiceField(
        choices=[
            ('skip_silent', 'Skip empty titles (no email)'),
            ('skip_and_notify', 'Skip empty titles and email the notification list'),
            ('hold_school', 'Do not add the school until every title is filled'),
        ],
        required=False,
        initial='skip_silent',
        label='If a required title is empty',
        help_text=(
            'Used when you add a school and nobody currently holds one of the titles '
            'in the signing order (for example there is no Principal).'
        ),
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    pdf_download = forms.ChoiceField(
        choices=[
            ('before_and_after', 'Before they sign, and after'),
            ('after_only', 'Only after they have signed'),
            ('never', 'Do not offer a PDF on the signing page'),
        ],
        required=False,
        initial='after_only',
        label='Let people download a PDF while signing',
        help_text='Controls whether the signing page includes a PDF download.',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    allow_change_requests = forms.ChoiceField(
        choices=[('Yes', 'Yes'), ('No', 'No')],
        required=False,
        initial='Yes',
        label='Let signers request changes',
        help_text='Yes shows a “Request Changes” button on the signing page.',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    hs_admin_can_view_signed_mous = forms.ChoiceField(
        choices=[('Yes', 'Yes'), ('No', 'No')],
        required=False,
        initial='No',
        label='High school admins can view signed agreements',
        help_text=(
            'Yes lets high school administrators download signed MOUs for their '
            'school from their portal.'
        ),
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    retention_years = forms.IntegerField(
        min_value=0,
        required=False,
        initial=DEFAULT_RETENTION_YEARS,
        label='How long signed agreements stay listed (years)',
        help_text=(
            'Signed MOUs older than this drop off the high school portal list. '
            'Enter 0 to show all of them. The files themselves are not deleted.'
        ),
        widget=forms.NumberInput(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    default_cron = forms.CharField(
        max_length=40,
        required=False,
        label='Default reminder schedule for new MOUs',
        help_text=(
            'Prefills the schedule box when you finalize an MOU that does not have '
            'one yet. It never changes an MOU that is already scheduled, and editing '
            'it here does not reschedule anything already sending. '
            'Example: 0 7 * * * means every day at 7:00 a.m.'
        ),
        widget=forms.TextInput(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No'),
        ('Debug', 'Debug')
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Enabled',
        help_text=(
            'Yes emails the people who need to sign. Debug sends those emails to '
            'the notification list instead, so you can test safely. No turns sending off.'
        ),
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    notify_address = forms.CharField(
        help_text=(
            'Staff emails that receive messages while Enabled is set to Debug. '
            'Also used when a required title is empty (if you chose to be notified) '
            'and when an MOU has no manager. Separate multiple addresses with commas.'
        ),
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

    reminder_email_subject = forms.CharField(
        max_length=200,
        required=False,
        help_text='Leave blank to reuse the first “please sign” subject on follow-up reminders.',
        label="Reminder Email Subject")

    reminder_email_message = forms.CharField(
        max_length=None,
        required=False,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Supports HTML. Used for the second and later “please sign” emails. Same placeholders as the first request. Leave blank to reuse that message. <a href="#" class="float-right" onClick="do_bulk_action(\'mou.email_settings\', \'reminder_email_message\')" >See Preview</a>',
        label="Reminder Email")

    heads_up_email = forms.ChoiceField(
        choices=[('Yes', 'Yes'), ('No', 'No')],
        required=False,
        initial='No',
        label='Send a heads-up to later signers',
        help_text=(
            'When the first person is asked to sign, everyone later in the order '
            'gets a one-time note that their turn is coming. That note does not '
            'include a signing link.'
        ),
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    heads_up_include_college = forms.ChoiceField(
        choices=[('Yes', 'Yes'), ('No', 'No')],
        required=False,
        initial='No',
        label='Include college staff in the heads-up',
        help_text=(
            'Yes also notifies college staff who sign after the first person. '
            'No sends it only to school and district signers. College staff still '
            'get the signing email when it is their turn.'
        ),
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    heads_up_email_subject = forms.CharField(
        max_length=200,
        required=False,
        help_text='Leave blank to skip the heads-up even if the setting above is Yes.',
        label='Heads-up email subject',
    )

    heads_up_email_message = forms.CharField(
        max_length=None,
        required=False,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text=(
            'Supports HTML. Sent once, with no signing link. Customize with '
            '{{signator_firstname}}, {{signator_lastname}}, {{highschool_name}}, '
            '{{role}}, {{mou_title}}, {{academic_year}}. '
            '<a href="#" class="float-right" onClick="do_bulk_action(\'mou.email_settings\', \'heads_up_email_message\')" >See Preview</a>'
        ),
        label='Heads-up email',
    )

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

        elif field_name == 'reminder_email_message':
            email = (
                email_settings.get('reminder_email_message')
                or email_settings.get('email_message')
            )
            subject = (
                email_settings.get('reminder_email_subject')
                or email_settings.get('email_subject')
            )

        elif field_name == 'heads_up_email_message':
            email = email_settings.get('heads_up_email_message')
            subject = email_settings.get('heads_up_email_subject')

        else:
            email = ''
            subject = ''

        email_template = Template(email or '')
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
            'academic_year': '2026-27',
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
        # cls.key follows the installed module path (mou.settings... vs
        # mou.mou.settings...). Read that first, then the other layout, so a
        # tenant that wrote settings under either key still resolves.
        keys = []
        for key in (cls.key, 'mou.settings.email_settings', 'mou.mou.settings.email_settings'):
            if key not in keys:
                keys.append(key)
        for key in keys:
            try:
                setting = Setting.objects.get(key=key)
                return setting.value or {}
            except Setting.DoesNotExist:
                continue
        return {}

    def install(self):
        defaults = {
            'is_active': "Debug",
            'available_shortcodes': [k for k, _ in AVAILABLE_SHORTCODES],
            'max_signator_weight': DEFAULT_MAX_SIGNATOR_WEIGHT,
            'allow_college_admin_any_weight': 'Yes',
            'vacant_role_policy': 'skip_silent',
            'pdf_download': 'after_only',
            'allow_change_requests': 'Yes',
            'hs_admin_can_view_signed_mous': 'No',
            'retention_years': DEFAULT_RETENTION_YEARS,
            'heads_up_email': 'No',
            'heads_up_include_college': 'No',
            'heads_up_email_subject': (
                'Coming up: you will be asked to sign the {{mou_title}}'
            ),
            'heads_up_email_message': (
                '<p>Dear {{signator_firstname}} {{signator_lastname}},</p>'
                '<p>The <strong>{{mou_title}}</strong> for '
                '<strong>{{highschool_name}}</strong> ({{academic_year}}) '
                'has been sent out for signatures.</p>'
                '<p>As <strong>{{role}}</strong>, you will be asked to sign when '
                'it is your turn. You will receive a separate email with a '
                'secure link at that time. No action is needed from you today.</p>'
                '<p>Thank you,<br>Office of Concurrent Enrollment</p>'
            ),
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
