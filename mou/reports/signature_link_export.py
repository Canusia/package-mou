import io, csv

from django import forms
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.encoding import force_str
from django.core.files.base import ContentFile, File

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import (
    export_to_excel, user_has_cis_role,
    user_has_highschool_admin_role, get_field
)

from ..models import MOU, MOUSignature

class signature_link_export(forms.Form):
    mou = forms.ModelChoiceField(
        queryset=None,
        label='MOU'
    )

    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

        self.fields['mou'].queryset = MOU.objects.all()

    def run(self, task, data):
        mou_id = data.get('mou')

        import datetime

        records = MOUSignature.objects.filter(
            signator_template__mou__id__in=mou_id,
            status='pending'
        )
        
        file_name = "pending_signatures-" + str(datetime.datetime.now().strftime('%m-%d-%Y')) + ".csv"
        
        fields = {
            'mou_title': 'MOU Title',
            'signator.first_name': 'Signature First Name',
            'signator.last_name': 'Signature Last Name',
            'signature_url': 'Signature URL',
            'status': 'Status'
        }

        http_response = export_to_excel(
            file_name,
            records,
            fields
        )

        path = "reports/" + str(datetime.datetime.now().strftime('%Y%m%d')) + f"/{task.id}/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(http_response.content))
        path = media_storage.url(path)

        return path
