import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code, validate_email_list
from cis.models.teacher import TeacherCourseCertificate

from cis.models.crontab import CronTab
from cis.models.settings import Setting

class SettingForm(forms.Form):

    teacher_course_status = forms.MultipleChoiceField(
        choices=TeacherCourseCertificate.STATUS_OPTIONS,
        label='Teacher Course Cert Status',
        help_text='These status(es) will be included in the teacher_list short code.',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'col-md-4 col-sm-12'})
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
        help_text='Supports HTML. Customize the message with {{highschool_name}}, {{signator_firstname}}, {{signature_lastname}}, {{mou_title}}, {{signature_url}}. <a href="#" class="float-right" onClick="do_bulk_action(\'mou.email_settings\', \'email_message\')" >See Preview</a>',
        label="Pending Signature Email")

    signed_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Signature Received - Email Subject")

    signed_email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Supports HTML. Customize the message with {{highschool_name}}, {{signator_firstname}}, {{signature_lastname}}, {{mou_title}}, {{mou_download_link}}. <a href="#" class="float-right" onClick="do_bulk_action(\'mou.email_settings\', \'signed_email_message\')" >See Preview</a>',
        label="Signature Received - Email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
        
        email_template = Template(email)
        context = Context({
            'signator_firstname': request.user.first_name,
            'signator_lastname': request.user.last_name,
            'highschool_name': "HS 1",
            'mou_title': "MOU Title",
            'signature_url': "https://someurl.com",
            'mou_download_link': 'https://downloadurl.com'
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
