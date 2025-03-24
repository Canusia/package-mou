import io, csv

from django import forms
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.encoding import force_str
from django.core.files.base import ContentFile, File

from django.http import HttpResponse
from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import (
    export_to_excel, user_has_cis_role,
    user_has_highschool_admin_role, get_field
)
 
from mou.models import MOU, MOUSignature

class mou_pdf_export(forms.Form):
    mou = forms.ModelChoiceField(
        queryset=None
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
            status='signed'
        )

        media_storage = PrivateMediaStorage()
        
        import os
        import zipfile
        from io import BytesIO

        path_prefix = f'reports/' + datetime.datetime.now().strftime('%Y%m%d') + f'/{task.id}/'

        ZIPFILE_NAME = f"mou_signature_export_" + datetime.datetime.now().strftime('%Y_%m_%d') + ".zip"
        b =  BytesIO()

        # records = records[0:5]
        with zipfile.ZipFile(b, 'w') as zf:            
            for record in records:
                row = []
                                    
                file_name = f'{record.highschool.name}_{record.signator.last_name}_{record.signator.first_name}.pdf'
                
                pdf = record.download_as_pdf(download=False)
                
                zf.writestr(file_name, pdf)

        zf.close()

        response = HttpResponse(b.getvalue(), content_type="application/x-zip-compressed")
        response['Content-Disposition'] = f'attachment; filename={ZIPFILE_NAME}'

        path = media_storage.save(path_prefix+ZIPFILE_NAME, ContentFile(response.getvalue()))
        path = media_storage.url(path)

        return path