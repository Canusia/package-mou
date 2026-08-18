import csv, io, datetime, uuid
from django import forms
from django.conf import settings
from django.forms import ValidationError
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from django.utils.safestring import mark_safe
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code, validate_cron

from form_fields import fields as FFields

from django_ckeditor_5.widgets import CKEditor5Widget as CKEditorWidget
from cis.models.customuser import CustomUser

from cis.utils import YES_NO_SELECT_OPTIONS
from .models import (
    MOU,
    MOUNote,
    MOUSignator, 
    MOUSignature
)

from cis.models.term import AcademicYear
from cis.models.highschool_administrator import HSPosition
from cis.models.district import DistrictPosition

# from announcement.models.announcement import Announcement, BulkMessage
# from announcement.apps import BMAILER_DS


class MOUFinalizeForm(forms.Form):

    title = forms.CharField(
        required=False,
        initial='Bulk Message Title',
        widget=forms.HiddenInput,
        help_text='Internal purposes only'
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='finalize'
    )

    academic_year = forms.ModelChoiceField(
        queryset=None,
        label='Academic Year',
        required=False
    )

    status = forms.ChoiceField(
        choices=MOU.STATUS_OPTIONS,
        help_text='Once the MOU is marked as \'Ready\' it will not be possible to edit it',
        required=True
    )

    send_after = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class':'col-md-8 col-sm-12'}),
        label='Schedule to Send Starting On',
        help_text='Select a date in the future to send.',
        input_formats=[('%m/%d/%Y')]
    )

    send_until = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class':'col-md-8 col-sm-12'}),
        label='Keep Sending Until',
        help_text='',
        input_formats=[('%m/%d/%Y')]
    )

    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay. Eg: 10 11 * * 1-3 to send it as 11:10am every Mon, Tue and Wed',
        label="When should the notification be sent?",
        validators=[validate_cron]
    )

    manager = forms.ModelChoiceField(
        queryset=None,
        label='MOU Manager',
        required=False,
        help_text='Who is emailed when a signer requests changes. If this is blank, the notification list is used instead.',
    )

    def __init__(self, request, record=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.record = record

        self.helper = FormHelper()
        self.helper.form_class = 'frm_ajax'
        self.helper.form_id = 'frm_mou_finalize'
        self.helper.form_method = 'POST'

        self.fields['title'].initial = record.title
        self.fields['status'].initial = record.status
        
        # if not record.meta.get('from_address'):
        #     self.fields['from_address'].initial = settings.DEFAULT_FROM_EMAIL
        # else:
        #     self.fields['from_address'].initial = record.meta.get('from_address')

        self.fields['academic_year'].queryset = AcademicYear.objects.all().order_by('-name')
        self.fields['academic_year'].initial = record.academic_year
        
        if record.send_on_after:
            self.fields['send_after'].initial = record.send_on_after.strftime('%m/%d/%Y')

        if record.send_until:
            self.fields['send_until'].initial = record.send_until.strftime('%m/%d/%Y')

        self.fields['cron'].initial = record.cron
        if not record.cron:
            from .settings.helpers import mou_cfg
            cfg = mou_cfg()
            if cfg.get('default_cron'):
                self.fields['cron'].initial = cfg.get('default_cron')

        if not record.send_on_after or not record.send_until:
            self._prefill_default_send_window(record)

        self.fields['manager'].queryset = CustomUser.objects.filter(
            groups__name='ce'
        ).order_by('first_name', 'last_name')
        self.fields['manager'].initial = record.manager_id

        if not record.can_edit():
            self.fields['status'].disabled = True
            self.fields['cron'].disabled = True
            self.fields['send_after'].disabled = True
            self.fields['send_until'].disabled = True
            self.fields['manager'].disabled = True

        if request:
            self.helper.form_action = reverse_lazy(
                'memo:memo', args=[record.id]
            )

    def _prefill_default_send_window(self, record):
        """Apply default MM/DD from settings using the current year.

        Only fills blanks so an already-scheduled MOU is not rewritten.
        """
        from .settings.helpers import mou_cfg
        cfg = mou_cfg()
        year = datetime.datetime.now().year
        if not record.send_on_after and cfg.get('default_send_after_mmdd'):
            mmdd = cfg.get('default_send_after_mmdd').strip()
            self.fields['send_after'].initial = f'{mmdd}/{year}' if '/' in mmdd and mmdd.count('/') == 1 else mmdd
        if not record.send_until and cfg.get('default_send_until_mmdd'):
            mmdd = cfg.get('default_send_until_mmdd').strip()
            self.fields['send_until'].initial = f'{mmdd}/{year}' if '/' in mmdd and mmdd.count('/') == 1 else mmdd

    def clean_status(self):
        if self.record.status == 'sent':
            raise ValidationError('The MOU has already been sent.')

        return self.cleaned_data.get('status')
   
    def save(self, request, record, commit=True):
        data = self.cleaned_data

        # record.title = data.get('title')
        record.status = data.get('status')

        if not record.meta:
            record.meta = {}

        record.send_on_after = data.get('send_after')
        record.send_until = data.get('send_until')
        record.cron = data.get('cron')

        academic_year = data.get('academic_year')
        if academic_year:
            record.academic_year = academic_year

        record.manager = data.get('manager')

        if commit:
            record.save()

        return record


class MOUSignatorDeleteForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='delete_signator'
    )

    ids = forms.MultipleChoiceField(
        choices=[],
        label='Signator(s)',
        widget=forms.CheckboxSelectMultiple
    )

    confirm = forms.BooleanField(
        required=True,
        label='I understand that by doing this any signatures added will be removed'
    )

    def __init__(self, ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if ids:
            records = MOUSignator.objects.filter(
                id__in=ids
            )

            record_choices = []
            for record in records:
                record_choices.append(
                    (
                        record.id,
                        f"{record.sexy_role} / {record.weight}"
                    )
                )
            self.fields['ids'].choices = record_choices
            self.fields['ids'].initial = ids
        else:
            record_choices = []
            for id in kwargs.get('data').getlist('ids'):
                record_choices.append(
                    (id, id)
                )

            self.fields['ids'].choices = record_choices
            self.fields['ids'].required = False

    def save(self):
        data = self.cleaned_data

        MOUSignator.objects.filter(
            id__in=data.get('ids')
        ).delete()

        return True

class MOUSignatureDeleteForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='delete_signature'
    )

    ids = forms.MultipleChoiceField(
        choices=[],
        label='Signature(s)',
        widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if ids:
            records = MOUSignature.objects.filter(
                id__in=ids
            )

            record_choices = []
            for record in records:
                record_choices.append(
                    (
                        record.id,
                        f"{record.highschool.name} / {record.signator} ({record.status})"
                    )
                )
            self.fields['ids'].choices = record_choices
            self.fields['ids'].initial = ids
        else:
            record_choices = []
            for id in kwargs.get('data').getlist('ids'):
                record_choices.append(
                    (id, id)
                )

            self.fields['ids'].choices = record_choices
            self.fields['ids'].required = False

    def save(self):
        data = self.cleaned_data

        MOUSignature.objects.filter(
            id__in=data.get('ids')
        ).delete()

        return True


class MOUSignatorForm(forms.Form):
    
    mou_id = forms.CharField(
        widget=forms.HiddenInput
    )

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='edit_mou_signator'
    )

    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

    role_type = forms.ChoiceField(
        choices=[('', 'Select')] + MOUSignator.ROLE_TYPES,
        help_text='',
        label='Role Type'
    )

    highschool_admin_role = forms.ChoiceField(
        choices=[],
        help_text='',
        required=False,
        label='School Admin Role'
    )

    district_admin_role = forms.ChoiceField(
        choices=[],
        help_text='',
        required=False,
        label='District Admin Role'
    )

    college_user = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='College Signer',
        help_text='The college staff member who signs this step on every school’s copy.',
        widget=forms.Select(attrs={'class': 'col-md-8 col-sm-12'}),
    )

    college_title = forms.CharField(
        max_length=200,
        required=False,
        label='College Signer Title',
        help_text='Shown next to their signature (for example, Vice President for Academic Affairs).',
    )

    weight = forms.ChoiceField(
        choices=[('', 'Select')],
        label='Signing order',
        help_text='1 signs first, then 2, and so on.',
    )

    complete_extra_form = forms.ChoiceField(
        choices=YES_NO_SELECT_OPTIONS,
        required=False,
        help_text='Will the person in this role complete the additional information form?',
        widget=forms.HiddenInput,
        initial='2'
    )

    class Media:
        js = [
            'js/mou_signator.js'
        ]

    def __init__(self, record, mou_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['highschool_admin_role'].choices = list(
            (pos.id, pos.name) for pos in HSPosition.objects.all().order_by('name')
        )

        self.fields['district_admin_role'].choices = list(
            (pos.id, pos.name) for pos in DistrictPosition.objects.all().order_by('name')
        )

        staff = CustomUser.objects.filter(
            is_active=True,
            is_staff=True,
        ).order_by('last_name')
        self.fields['college_user'].queryset = staff

        from .settings.helpers import get_max_signator_weight
        max_weight = get_max_signator_weight()
        self.fields['weight'].choices = [('', 'Select')] + [(i, i) for i in range(1, max_weight + 1)]
        self.fields['weight'].help_text = (
            f'1 signs first, then 2, and so on. You can use 1 through {max_weight}.'
        )

        self.fields['mou_id'].initial = mou_id
        
        if record:
            self.fields['id'].initial = record.id

            self.fields['weight'].initial = record.weight
            self.fields['role_type'].initial = record.role_type
            self.fields['highschool_admin_role'].initial = record.role
            self.fields['district_admin_role'].initial = record.role
            self.fields['college_user'].initial = record.college_user_id
            self.fields['college_title'].initial = record.title

            self.fields['complete_extra_form'].initial = record.meta.get('complete_extra_form')
        else:
            self.fields['id'].initial = -1

    def clean_weight(self):
        weight = self.cleaned_data.get('weight')

        if weight == '':
            raise ValidationError('Please choose a signing order')

        from .settings.helpers import college_admin_any_weight_allowed
        if self.cleaned_data.get('role_type') == 'college_admin':
            if not college_admin_any_weight_allowed() and int(weight) < 3:
                raise ValidationError(
                    'College staff can only be placed at steps 3 or 4. '
                    'Turn on “College staff can sign at any step” in MOU settings to allow other positions.'
                )
            
        return weight

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('role_type') == 'college_admin' and not cleaned.get('college_user'):
            self.add_error('college_user', 'Select the college staff member who will sign this step.')
        return cleaned
    
    def save(self, request, mou, commit=True):
        data = self.cleaned_data

        if data.get('id') == '-1':
            record = MOUSignator(mou=mou, created_by=request.user, meta={})
        else:
            record = MOUSignator.objects.get(pk=data.get('id'))
        
        record.weight = data.get('weight')
        record.role_type = data.get('role_type')

        if data.get('role_type') == 'highschool_admin':
            record.role = data.get('highschool_admin_role')
            record.college_user = None
            record.title = ''
        elif data.get('role_type') == 'district_admin':
            record.role = data.get('district_admin_role')
            record.college_user = None
            record.title = ''
        elif data.get('role_type') == 'college_admin':
            if data.get('id') == '-1':
                record.role = uuid.uuid4()
            record.college_user = data.get('college_user')
            record.title = data.get('college_title') or ''

        record.meta['complete_extra_form'] = data.get('complete_extra_form')

        if commit:
            record.save()

        return record
    
class MOUEditorForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='edit_mou'
    )

    title = forms.CharField(
        required=True,
        validators=[validate_html_short_code],
        widget=forms.TextInput(
            attrs={
                'class': 'col-8'
            }
        )
    )

    mou_text = forms.CharField(
        widget=CKEditorWidget(
            attrs={"class": "django_ckeditor_5"}
        ),
        label='MOU Text',
        required=False,
        validators=[validate_html_short_code]
    )

    def save(self, request, record, commit=True):
        data = self.cleaned_data

        record.title = data.get('title')
        record.mou_text = data.get('mou_text')
        
        if not record.meta:
            record.meta = {}
        # record.meta['subject'] = data.get('subject')

        record.save()
        return record

    def __init__(self, request, record=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.form_class = 'frm_ajax'
        self.helper.form_id = 'frm_editor'
        self.helper.form_method = 'POST'

        self.fields['title'].initial = record.title
        self.fields['mou_text'].initial = record.mou_text
        self.fields['mou_text'].help_text = self._build_mou_text_help()

        if not record.can_edit():
            self.fields['title'].disabled = True
            self.fields['mou_text'] = FFields.LongLabelField(
                required=False,
                label=mark_safe(record.mou_text),
                widget=FFields.LongLabelWidget(
                    attrs={
                        'class':'border-0 bg-light h-100'
                    }
                )
            )

        if request:
            self.helper.form_action = reverse_lazy(
                'memo:memo', args=[record.id]
            )

    @staticmethod
    def _build_mou_text_help():
        from .settings.email_settings import email_settings, AVAILABLE_SHORTCODES

        cfg = email_settings.from_db()
        configured = cfg.get('available_shortcodes')
        if configured is None:
            allowed = {k for k, _ in AVAILABLE_SHORTCODES}
        else:
            allowed = set(configured)

        if not allowed:
            return mark_safe(
                'No shortcodes are currently enabled. Add them under '
                '<em>Settings &rarr; MOU Notifications &rarr; Available Shortcodes</em>.'
            )

        items = [label for key, label in AVAILABLE_SHORTCODES if key in allowed]
        body = '<ul class="mb-1">' + ''.join(f'<li><code>{label}</code></li>' for label in items) + '</ul>'
        return mark_safe(
            'Available shortcodes (from <em>Settings &rarr; MOU Notifications &rarr; '
            'Available Shortcodes</em>):' + body
        )


class MOUInitForm(forms.Form):
    group_by = forms.ChoiceField(
        choices=MOU.GROUP_BY_CHOICES
    )

    title = forms.CharField(
        required=True,
        label='MOU - Title'
    )

    academic_year = forms.ModelChoiceField(
        queryset=None,
        label='Academic Year'
    )

    id = forms.CharField(
        required=False,
        label='ID',
        widget=forms.HiddenInput
    )

    class Media:
        js = [
            'js/bulk_mailer.js'
        ]

    def __init__(self, request, record=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.fields['academic_year'].queryset = AcademicYear.objects.all().order_by('-name')

        self.helper = FormHelper()
        self.helper.form_class = 'frm_ajax'
        self.helper.form_id = 'frm_add_new_memo'
        self.helper.form_method = 'POST'

        self.helper.add_input(Submit('submit', 'Save and Continue'))

    def save(self, request, commit=True):

        data = self.cleaned_data
        record = MOU(
            group_by=data.get('group_by'),
            title=data.get('title'),
            academic_year=data.get('academic_year'),
            created_by=request.user
        )

        record.meta = {}
        
        if commit:
            record.save()
        return record

class MOUSignatureForm(forms.Form):

    poc_header = FFields.ReadOnlyField(
        required=False,
        label=mark_safe('<h4>POC Header</h4>'),
        initial='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )
    poc_name = forms.CharField(
        required=True,
        label='POC Name'
    )

    poc_email = forms.CharField(
        required=True,
        label='POC Email'
    )

    poc_phone = forms.CharField(
        required=True,
        label='POC Phone #'
    )

    tuition_manager_header = FFields.ReadOnlyField(
        required=False,
        label=mark_safe('<h4>Tuition Manager Header</h4>'),
        initial='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    tuition_manager_name = forms.CharField(
        required=True,
        label='Tuition Manager Name'
    )

    tuition_manager_email = forms.CharField(
        required=True,
        label='Tuition Manager Email'
    )

    tuition_manager_phone = forms.CharField(
        required=True,
        label='Tuition Manager Phone #'
    )

    SOURCE_OF_FUNDS = [
        ('parent_pay', 'Parent pays the entire tuition to the school and school sends one check.'),
        ('split_pay', 'Parents and school/district each pay partial, then school sends one check.'),
        ('school_pay', 'School/district pays entire tuition. Parents will be sent a 1098 form by the IRS in late January. Schools that plan to use SCA funds are responsible for paying tuition directly to LSU'),
        ('other', 'Other')
    ]

    source_of_funds = forms.ChoiceField(
        choices=SOURCE_OF_FUNDS,
        widget=forms.RadioSelect
    )
    
    parent_pay_percentage = forms.FloatField(
        required=False,
        label='Parent Pay Percentage',
        widget=forms.NumberInput(attrs={
            'class': 'col-6'
        })
    )

    school_pay_percentage = forms.FloatField(
        required=False,
        label='School Pay Percentage',
        widget=forms.NumberInput(attrs={
            'class': 'col-6'
        })
    )

    other_pay = forms.CharField(
        required=False,
        label='If other, please describe'
    )
    
    name = forms.CharField(
        required=True,
        label='Your Name',
        disabled=True
    )

    email = forms.CharField(
        required=True,
        label='Your Email',
        disabled=True
    )

    position = forms.CharField(
        required=True,
        label='Your Position/Role',
        disabled=True
    )


    confirm_term = forms.CharField(
        label='I have read the terms of the MOU',
        required=True,
        widget=forms.CheckboxInput(
            attrs={
                'class': 'bg-primary'
            }
        )
    )

    signature = FFields.SignatureField(
        label='Signature',
        required=True,
        error_messages={
            'required':'Please sign in the box'
        },
        widget=FFields.SignatureWidget
    )

    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['name'].initial = f'{record.signator.first_name} {record.signator.last_name}'
        self.fields['position'].initial = record.signator_template.sexy_role
        self.fields['email'].initial = record.signator.email

        if record.signator_template.complete_extra_form == 'No':
            fields_to_remove = [
                'poc_header',
                'poc_name',
                'poc_email',
                'poc_phone',
                'tuition_manager_header',
                'tuition_manager_name',
                'tuition_manager_email',
                'tuition_manager_phone',
                'source_of_funds'
            ]

            for field in fields_to_remove:
                del self.fields[field]

    def save(self, record):
        data = self.cleaned_data

        # save this to the mou
        if record.signator_template.complete_extra_form == 'Yes':
            for field, value in data.items():
                record.signator_template.mou.meta[field] = value
            record.signator_template.mou.save()

        for field, value in data.items():
            record.meta[field] = value

        record.meta['signature'] = data.get('signature')
        record.meta['signed_on'] = datetime.datetime.now().strftime('%m/%d/%Y %I:%M %p')

        record.mark_as_signed(commit=False)

        record.save()
        return record
    
    def clean(self):
        cleaned_data = super().clean()

        if not cleaned_data.get('signature', None):
            raise ValidationError(_('Signature is required. Please sign in the box below.'), code='invalid')

        return cleaned_data


class MOURequestChangesForm(forms.Form):

    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='request_changes',
    )

    change_request_comment = forms.CharField(
        label='What changes would you like to see in this MOU?',
        required=True,
        widget=forms.Textarea(attrs={'rows': 6, 'class': 'col-12'}),
        help_text='Describe the language or terms you would like changed. The MOU manager will follow up.',
    )

    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.record = record

        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.form_id = 'frm_mou_request_changes'
        self.helper.form_action = reverse_lazy(
            'mou:sign', kwargs={'signature_id': record.id}
        )

    def save(self, signature):
        comment = self.cleaned_data['change_request_comment']

        if not signature.meta:
            signature.meta = {}
        signature.meta['change_request_comment'] = comment
        signature.meta['change_requested_on'] = datetime.datetime.now().strftime('%m/%d/%Y %I:%M %p')
        signature.status = 'changes_requested'
        signature.save()

        # Audit trail: MOUNote on the parent MOU.
        MOUNote.objects.create(
            meo=signature.signator_template.mou,
            createdby=signature.signator,
            note=(
                f'Change request from {signature.signator.first_name} '
                f'{signature.signator.last_name} '
                f'({signature.highschool.name}): {comment}'
            ),
            meta={'type': 'change_request'},
        )

        signature.send_change_request_notification()
        return signature


class MOUSignatureChangeStatusForm(forms.Form):
    ids = forms.MultipleChoiceField(
        required=False,
        label='Records to Update',
        widget=forms.CheckboxSelectMultiple,
        choices=[]
    )
    
    new_status = forms.ChoiceField(
        required=False,
        label='Change Signature Status To',
        choices=MOUSignature.STATUS_OPTIONS
    )

    action = forms.CharField(
        widget=forms.HiddenInput
    )

    def __init__(self, ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['action'].initial = kwargs.get('action', 'change_signature_status')
        if ids:
            records = MOUSignature.objects.filter(
                id__in=ids
            )

            record_choices = []
            for record in records:
                record_choices.append(
                    (
                        record.id,
                        f"{record.highschool.name} - {record.signator} ({record.status})"
                    )
                )
            self.fields['ids'].choices = record_choices
            self.fields['ids'].initial = ids
        else:
            record_choices = []
            for id in kwargs.get('data').getlist('ids'):
                record_choices.append(
                    (id, id)
                )

            self.fields['ids'].choices = record_choices
            self.fields['ids'].required = False

    def save(self, request=None):
        data = self.cleaned_data

        new_status = data.get('new_status')

        for id in data.get('ids'):
            try:
                record = MOUSignature.objects.get(
                    id=id
                )

                record.status = new_status
                record.save()
            except Exception as e:
                ...
    
class AddHighSchoolForm(forms.Form):
    highschools = forms.ModelMultipleChoiceField(
        required=True,
        label='Select High School(s) to Add',
        widget=forms.CheckboxSelectMultiple,
        queryset=None
    )
    
    action = forms.CharField(
        widget=forms.HiddenInput
    )

    mou_id = forms.CharField(
        widget=forms.HiddenInput
    )

    def __init__(self, mou_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from cis.models.highschool import HighSchool
        # Validate against the full queryset (any status). The "Add High
        # School(s)" modal shows the status column so the user can decide
        # whether to include non-Active schools; the form silently dropping
        # them based on status would be surprising.
        self.fields['highschools'].queryset = HighSchool.objects.order_by('name')

        self.fields['action'].initial = kwargs.get('action', 'add_highschools')
        self.fields['mou_id'].initial = mou_id

    def _resolve_college_user(self, signator, email_settings):
        """Prefer the user stored on the signator; fall back to legacy weight 3/4 settings."""
        if signator.college_user_id:
            return signator.college_user
        weight = signator.weight
        user_id = None
        if weight == 3:
            user_id = email_settings.get('college_administrator_1')
        elif weight == 4:
            user_id = email_settings.get('college_administrator_2')
        if not user_id:
            return None
        return CustomUser.objects.filter(id=user_id).first()

    def _notify_vacant_roles(self, mou, misses):
        from django.template.loader import get_template
        from mailer import send_html_mail
        from .settings.helpers import notification_recipients, notify_address_list
        from .settings.email_settings import email_settings as mou_settings

        cfg = mou_settings.from_db()
        intended = []
        if mou.manager and mou.manager.email:
            intended.append(mou.manager.email)
        intended.extend(notify_address_list(cfg))
        # Deduplicate while preserving order
        seen = set()
        intended = [a for a in intended if not (a in seen or seen.add(a))]
        to = notification_recipients(intended, cfg)
        if not to:
            return

        lines = []
        for miss in misses:
            lines.append(
                f"{miss['highschool']} — {miss['role']} (step {miss['weight']})"
            )
        body = (
            f"<p>These required titles were empty when schools were added to "
            f"<strong>{mou.title}</strong>:</p><ul>"
            + ''.join(f"<li>{line}</li>" for line in lines)
            + "</ul>"
        )
        html_body = get_template('cis/email.html').render({'message': body})
        send_html_mail(
            f'MOU missing signer — {mou.title}',
            '\n'.join(lines),
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to,
        )
        
    def save(self, request=None):
        from cis.models.highschool_administrator import HSAdministratorPosition
        from cis.models.district import DistrictAdministratorPosition
        from .settings.email_settings import email_settings as mou_settings
        from .settings.helpers import vacant_role_policy

        data = self.cleaned_data
        mou = MOU.objects.get(pk=data.get('mou_id'))
        cfg = mou_settings.from_db()
        policy = vacant_role_policy(cfg)

        signators = MOUSignator.objects.filter(mou=mou).order_by('weight')

        result = {}
        misses = []
        for highschool in data.get('highschools'):
            result[highschool.code] = {'signator': []}
            resolved = []
            school_misses = []

            for signator in signators:
                signee = None
                role = signator.sexy_role

                if signator.role_type == 'highschool_admin':
                    admin_positions = HSAdministratorPosition.objects.filter(
                        position__id=signator.role,
                        highschool=highschool,
                        status__iexact='active'
                    )
                    if admin_positions:
                        signee = admin_positions[0].hsadmin.user
                        role = admin_positions[0].position.name
                elif signator.role_type == 'district_admin':
                    admin_positions = DistrictAdministratorPosition.objects.filter(
                        position__id=signator.role,
                        district=highschool.district,
                        status__iexact='active'
                    )
                    if admin_positions:
                        # cis names this district_admin; older copies used hsadmin.
                        holder = admin_positions[0]
                        admin_obj = getattr(holder, 'district_admin', None) or getattr(holder, 'hsadmin', None)
                        signee = admin_obj.user if admin_obj else None
                        role = holder.position.name
                elif signator.role_type == 'college_admin':
                    signee = self._resolve_college_user(signator, cfg)
                    role = signator.title or 'College Administrator'

                if not signee:
                    school_misses.append({
                        'highschool': highschool.name,
                        'role': role,
                        'weight': signator.weight,
                        'role_type': signator.role_type,
                    })
                    result[highschool.code]['signator'].append({
                        signator.role_type: f'Not found for {signator.weight}'
                    })
                else:
                    resolved.append((signator, signee, role))

            if school_misses and policy == 'hold_school':
                misses.extend(school_misses)
                result[highschool.code]['held'] = True
                continue

            misses.extend(school_misses)

            for signator, signee, role in resolved:
                if MOUSignature.objects.filter(
                    highschool=highschool,
                    signator=signee,
                    signator_template=signator
                ).exists():
                    result[highschool.code]['signator'].append({
                        signator.role_type: str(signee) + ' exists'
                    })
                else:
                    MOUSignature.objects.create(
                        highschool=highschool,
                        signator=signee,
                        signator_template=signator,
                        status='',
                        meta={'role': role},
                    )
                    result[highschool.code]['signator'].append({
                        signator.role_type: str(signee) + ' added'
                    })

        mou.initialize_signature_status()
        if misses and policy == 'skip_and_notify':
            self._notify_vacant_roles(mou, misses)
        result['_misses'] = misses
        result['_policy'] = policy
        return result
