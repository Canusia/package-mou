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

from announcement.models.announcement import Announcement, BulkMessage
from announcement.apps import BMAILER_DS


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

    status = forms.ChoiceField(
        choices=MOU.STATUS_OPTIONS,
        help_text='Once the MOU is marked as \'Ready\' it will not be possible to edit it',
        required=True
    )

    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay. Eg: 10 11 * * 1-3 to send it as 11:10am every Mon, Tue and Wed',
        label="When should the notification be sent?",
        validators=[validate_cron]
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

        if record.send_on_after:
            self.fields['send_after'].initial = record.send_on_after.strftime('%m/%d/%Y')

        if record.send_until:
            self.fields['send_until'].initial = record.send_until.strftime('%m/%d/%Y')

        self.fields['cron'].initial = record.cron


        if not record.can_edit():
            self.fields['status'].disabled = True
            self.fields['cron'].disabled = True
            self.fields['send_after'].disabled = True
            self.fields['send_until'].disabled = True

        if request:
            self.helper.form_action = reverse_lazy(
                'memo:memo', args=[record.id]
            )

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

    weight = forms.ChoiceField(
        choices=[('','Select')] + [(i, i)for i in range(1,5)],
        help_text='Lower weight is required to sign first. If choosing College Administrator, please select 3 or 4',
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

        self.fields['mou_id'].initial = mou_id
        
        if record:
            self.fields['id'].initial = record.id

            self.fields['weight'].initial = record.weight
            self.fields['role_type'].initial = record.role_type
            self.fields['highschool_admin_role'].initial = record.role
            self.fields['district_admin_role'].initial = record.role

            self.fields['complete_extra_form'].initial = record.meta.get('complete_extra_form')
        else:
            self.fields['id'].initial = -1

    def clean_weight(self):
        weight = self.cleaned_data.get('weight')

        if weight == '':
            raise ValidationError('Please select a weight')

        if self.cleaned_data.get('role_type') == 'college_admin':
            if int(weight) < 3:
                raise ValidationError('College Administrator must be 3 or 4')
            
        return weight
    
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
        elif data.get('role_type') == 'district_admin':
            record.role = data.get('district_admin_role')
        elif data.get('role_type') == 'college_admin':
            record.role = uuid.uuid4()

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
        help_text='Customize with {{signature_1}}, {{signature_2}}, {{signature_3}}, {{signature_4}}, {{highschool_name}}, {{highschool_ceeb}}, {{academic_year}}, {{teacher_list}}, {{choice_teacher_list}}, {{pathways_teacher_list}}, {{pathways_course_list}}, {{choice_course_list}}',
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
        self.fields['highschools'].queryset = HighSchool.objects.filter(
            status__iexact='active'
        ).order_by('name')

        self.fields['action'].initial = kwargs.get('action', 'add_highschools')
        self.fields['mou_id'].initial = mou_id
        
    def save(self, request=None):
        from cis.models.highschool_administrator import HSAdministratorPosition
        from cis.models.district import DistrictAdministratorPosition
        data = self.cleaned_data

        mou = MOU.objects.get(pk=data.get('mou_id'))
        
        signators = MOUSignator.objects.filter(
            mou=mou
        ).order_by('weight')

        result = {}
        for highschool in data.get('highschools'):
            result[highschool.code] = {
                'signator': []
            }

            for signator in signators:
                admin_positions = None

                if signator.role_type == 'highschool_admin':
                    # get the active person 
                    admin_positions = HSAdministratorPosition.objects.filter(
                        position__id=signator.role,
                        highschool=highschool,
                        status__iexact='active'
                    )
                elif signator.role_type == 'district_admin':
                    admin_positions = DistrictAdministratorPosition.objects.filter(
                        position__id=signator.role,
                        district=highschool.district,
                        status__iexact='active'
                    )
                elif signator.role_type == 'college_admin':
                    weight = signator.weight

                    # add college administrators if listed in Settings
                    from .settings.email_settings import email_settings as mou_settings
                    email_settings = mou_settings.from_db()
                    if weight == 3:
                        admin_positions = CustomUser.objects.filter(
                            id=email_settings.get('college_administrator_1', 1)
                        )
                    elif weight == 4:
                        admin_positions = CustomUser.objects.filter(
                            id=email_settings.get('college_administrator_2', 1)
                        )
                    print(admin_positions, type(admin_positions))

                if not admin_positions:
                    result[highschool.code]['signator'].append({
                        signator.role_type: f'Not found for {signator.weight}'
                    })
                else:
                    if signator.role_type in ['highschool_admin', 'district_admin']:
                        signee = admin_positions[0].hsadmin.user
                        role = admin_positions[0].position.name
                    else:
                        signee = admin_positions[0]
                        role = 'College Administrator'

                    print(f'Adding {signator.weight} {signator.role_type} {signee} to {highschool.name}')
                    if MOUSignature.objects.filter(
                        highschool=highschool,
                        signator=signee,
                        signator_template=signator
                    ).exists():
                        result[highschool.code]['signator'].append({
                            signator.role_type: str(signee) + ' exists'
                        })
                    else:
                        signature = MOUSignature(
                            highschool=highschool,
                            signator=signee,
                            signator_template=signator,
                            status='',
                            meta={
                                'role': role,
                            }
                        )

                        signature.save()
                        result[highschool.code]['signator'].append({
                            signator.role_type: str(signee) + ' added'
                        })

        mou.initialize_signature_status()
        return result
