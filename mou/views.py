from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.utils.safestring import mark_safe
from django.urls import reverse_lazy
from django.views.decorators.clickjacking import xframe_options_exempt

from django.template.context_processors import csrf
from django.views.decorators.csrf import csrf_exempt

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from cis.models.settings import Setting
from cis.utils import (
    user_has_cis_role,
    user_has_highschool_admin_role
)

from crispy_forms.utils import render_crispy_form

from .models import MOU, MOUNote, MOUSignature, MOUSignator
from .forms import (
    MOUInitForm,
    MOUEditorForm,
    MOUFinalizeForm,
    MOUSignatorForm,
    MOUSignatureChangeStatusForm,
    MOUSignatureForm,
    MOUSignatorDeleteForm,
    MOUSignatureDeleteForm
)

from cis.menu import (
    cis_menu, draw_menu, STUDENT_MENU, HS_ADMIN_MENU
)

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import (
    MOUSerializer,
    MOUSignatorSerializer,
    MOUSignatureSerializer
)

class MOUViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MOUSerializer

    def get_queryset(self):
        records = MOU.objects.all()
        return records

class MOUSignatorViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MOUSignatorSerializer

    def get_queryset(self):
        records = MOUSignator.objects.all()

        if self.request.GET.get('mou_id'):
            records = records.filter(
                mou__id=self.request.GET.get('mou_id')
            )
        return records

class MOUSignatureViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MOUSignatureSerializer

    def get_queryset(self):
        records = MOUSignature.objects.all()

        if self.request.GET.get('mou_id'):
            records = records.filter(
                signator_template__mou__id=self.request.GET.get('mou_id')
            )
        return records


@user_passes_test(user_has_cis_role, login_url='/')
def mou_add_new(request):
    if request.method == 'POST':
        """
        Add New
        """
        form = MOUInitForm(
            request=request, record=None, data=request.POST, files=request.FILES
        )

        if form.is_valid():
            record = form.save(request=request, commit=True)

            data = {
                'status':'success',
                'message':'Successfully started MOU. Click "Ok" to continue.',
                'redirect_to': str(record.ce_url),
                'action': 'redirect_to'
            }
            return JsonResponse(data)
        else:
            return JsonResponse({
                'message': 'Please correct the errors and try again',
                'errors': form.errors.as_json()
            }, status=400)


@user_passes_test(user_has_cis_role, login_url='/')
def mou_preview(request, record_id):

    record = get_object_or_404(MOU, pk=record_id)

    message = record.preview()
    return render(
        request,
        'cis/email.html',
        {
            'message': message
        }
    )

@user_passes_test(user_has_cis_role, login_url='/')
def mou_delete(request, record_id):

    record = get_object_or_404(MOU, pk=record_id)

    if not record.can_edit:
        return JsonResponse({
            'message': 'Unable to complete request',
            'errors': 'The MOU has already been sent'
        }, status=400)
    
    try:
        MOUSignator.objects.filter(mou=record).delete()
        record.delete()

        data = {
            'status':'success',
            'message':'Successfully deleted record.',
            'redirect_to': str(reverse_lazy('mou_ce:all'))
        }
        status = 200
    except Exception as e:
        data = {
            'message': 'Unable to complete request',
            'errors': str(e)
        }
        status = 400

    return JsonResponse(data, status=status)

def sign_mou(request, signature_id):
    signature = get_object_or_404(MOUSignature, pk=signature_id)

    # if not signature.is_ready_to_be_signed():
    #     from django.core.exceptions import BadRequest

    #     raise BadRequest('The signature record is not ready to be signed.')
    
    # show the mou and collect signature
    template = 'mou/sign_mou.html'
    form = MOUSignatureForm(
        record=signature
    )

    if request.method == 'POST':
        form = MOUSignatureForm(
            record=signature,
            data=request.POST
        )

        if form.is_valid():
            signature = form.save(signature)

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully signed MOU. A confirmation email has been sent to you.',
                'list-group-item-success'
            )
            return redirect('mou:sign', signature_id=signature_id)
        else:
            messages.add_message(
                request,
                messages.ERROR,
                'Please correct the errors and try again ' + str(form.errors),
                'list-group-item-danger'
            )

    context = {
        'record': signature,
        'form': form,
        'page_title': f'{signature.mou_title} - {signature.signator}'
    }

    return render(request, template, context)
sign_mou.login_required=False

def do_bulk_action(request):
    action = request.GET.get('action')

    if request.method == 'POST':
        action = request.POST.get('action')
        
    if action == 'change_signature_status':
        return manage_signature_status(request)
    
    if action == 'delete_signator':
        return delete_signator(request)
    
    if action == 'add_signator':
        return add_signator(request)
    
    if action == 'edit_mou_signator':
        return add_signator(request)
    
    if action == 'delete_signature':
        return delete_signature(request)
    
    if action == 'add_highschools':
        return add_highschools(request)
    
    elif action == 'get_signature_link':
        return get_signature_link(request)
    
    elif action == 'send_signature_link':
        return send_signature_link(request)

    data = {
        'status': 'success',
        'message': 'invalid action passed'
    }
    return JsonResponse(data)

def manage_signature_status(request):
    template = 'mou/bulk_action.html'

    if request.method == 'POST':

        form = MOUSignatureChangeStatusForm(data=request.POST)

        if form.is_valid():
            status = form.save()

            data = {
                'status':'success',
                'message':'Successfully updated records',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    ids = request.GET.getlist('ids[]')
    form = MOUSignatureChangeStatusForm(ids)
    context = {
        'title': 'Change MOU Signature Status',
        'form': form,
        'show_form': True,
        'form_submit_button_title': 'Update Status',
        'form_header': mark_safe('<p class="alert alert-info">Select a new status and click \'Update Status\'</p>')
    }
    
    return render(request, template, context)

def add_highschools(request):
    template = 'mou/bulk_action.html'

    from .forms import AddHighSchoolForm

    if request.method == 'POST':

        mou_id = request.POST.get('mou_id')
        form = AddHighSchoolForm(mou_id=mou_id, data=request.POST)

        if form.is_valid():
            status = form.save()

            data = {
                'status':'success',
                'message':'Successfully processed request',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    mou_id = request.GET.get('mou_id')
    form = AddHighSchoolForm(mou_id)
    context = {
        'title': 'Add High School(s)',
        'form': form,
        'show_form': True,
        'form_submit_button_title': 'Save',
        'form_header': mark_safe('<p class="alert alert-info">Select high school(s) from the list to add</p>')
    }
    
    return render(request, template, context)

def add_signator(request):
    template = 'mou/bulk_action.html'

    from .forms import MOUSignatorForm

    if request.method == 'POST':

        mou_id = request.POST.get('mou_id')
        id = request.POST.get('id')
        mou = MOU.objects.get(pk=mou_id)

        if id != '-1':
            record = MOUSignator.objects.get(pk=id)
        else:
            record = None

        form = MOUSignatorForm(record=record, mou_id=mou_id, data=request.POST)

        if form.is_valid():
            status = form.save(request, mou)

            data = {
                'status':'success',
                'message':'Successfully processed request',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    record = None
    mou_id = request.GET.get('mou_id')
    if request.GET.get('id'):
        record = MOUSignator.objects.get(pk=request.GET.get('id'))
        
    form = MOUSignatorForm(record=record, mou_id=mou_id)

    delete_url = ''
    if record:
        delete_url = str(reverse_lazy(
            'mou_ce:mou',
            kwargs={
                'record_id': mou_id
            }
        )) + f'action=delete_signator&signator_id={record.id}'

    context = {
        'title': 'Manage Signator',
        'form': form,
        'show_form': True,
        # 'allow_delete': True if record else False,
        'form_submit_button_title': 'Save',
        # 'delete_url': mark_safe(delete_url),
        'form_header': mark_safe('')
    }
    
    return render(request, template, context)

def delete_signator(request):
    template = 'mou/bulk_action.html'

    if request.method == 'POST':

        form = MOUSignatorDeleteForm(data=request.POST)

        if form.is_valid():
            status = form.save()

            data = {
                'status':'success',
                'message':'Successfully deleted records',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    ids = request.GET.getlist('ids[]')
    form = MOUSignatorDeleteForm(ids)
    context = {
        'title': 'Delete Selected MOU Signator(s)',
        'form': form,
        'show_form': True,
        'form_submit_button_title': 'Confirm & Delete',
        'form_header': mark_safe('<p class="alert alert-info">This will remove the selected signator(s). This action cannot be undone. Any signatures that have been added to the MOU will ALSO be deleted.</p>')
    }
    
    return render(request, template, context)

def delete_signature(request):
    template = 'mou/bulk_action.html'

    if request.method == 'POST':

        form = MOUSignatureDeleteForm(data=request.POST)

        if form.is_valid():
            status = form.save()

            data = {
                'status':'success',
                'message':'Successfully deleted records',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    ids = request.GET.getlist('ids[]')
    form = MOUSignatureDeleteForm(ids)
    context = {
        'title': 'Delete Selected MOU Signature(s)',
        'form': form,
        'show_form': True,
        'form_submit_button_title': 'Confirm & Delete',
        'form_header': mark_safe('<p class="alert alert-info">This will remove the selected signature(s). This action cannot be undone.</p>')
    }
    
    return render(request, template, context)

def get_signature_link(request):
    template = 'mou/bulk_action.html'

    ids = request.GET.getlist('ids[]')
    links = []
    for id in ids:
        signature = MOUSignature.objects.get(pk=id)
        links.append(
            f'{signature.signator} - {signature.signature_url}'
        )
    context = {
        'title': 'MOU Signature Link(s)',
        'form_header': mark_safe(
            '<p class="alert alert-info">Copy and send the link(s)</p> ' + '<br>'.join(links)
        )
    }
    
    return render(request, template, context)

def send_signature_link(request):
    template = 'mou/bulk_action.html'

    ids = request.GET.getlist('ids[]')
    links = []
    for id in ids:
        signature = MOUSignature.objects.get(pk=id)
        if signature.status == MOUSignature.STATUS_PENDING:
            signature.send_notification()

            links.append(f'{signature.signator.first_name} {signature.signator.last_name} - ({signature.signator.email})')

        else:
            links.append(f'{signature.signator.first_name} {signature.signator.last_name} - No email sent. Please review status and try again')

    context = {
        'title': 'MOU Signature Email(s)',
        'form_header': mark_safe(
            '<p class="alert alert-info">Sent email(s) to </p> ' + '<br>'.join(links)
        )
    }
    
    return render(request, template, context)

def mou_signature_asPDF(self, signature_id):
    record = get_object_or_404(MOUSignature, pk=signature_id)
    return record.download_as_pdf()
mou_signature_asPDF.login_required=False

@csrf_exempt
@user_passes_test(user_has_cis_role, login_url='/')
def mou(request, record_id):
    menu = draw_menu(cis_menu, 'highschools', 'mous')
    template = 'mou/mou.html'
    
    record = get_object_or_404(MOU, pk=record_id)
    form = MOUEditorForm(request, record)
    finalize_form = MOUFinalizeForm(request, record)
    
    form_signator = MOUSignatorForm(record=None)
    signator = None

    if request.GET.get('action') == 'edit_signator':
        signator_id = request.GET.get('signator_id')
        signator = MOUSignator.objects.get(pk=signator_id)

        form_signator = MOUSignatorForm(record=signator)

    if request.GET.get('action') == 'delete_signator':
        signator_id = request.GET.get('signator_id')
        signator = MOUSignator.objects.get(pk=signator_id)

        signator.delete()
        
        data = {
            'status':'success',
            'message':'Successfully processed your rquest.',
            'action': 'reload_table'
        }
        return JsonResponse(data)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'finalize':
            form = MOUFinalizeForm(
                request,
                record,
                request.POST
            )

            if form.is_valid():
                record = form.save(request=request, record=record, commit=True)

                data = {
                    'status':'success',
                    'message':'Successfully updated MOU.',
                    'redirect_to': str(record.ce_url),
                    'action': 'redirect_to'
                }
                return JsonResponse(data)
            else:
                return JsonResponse({
                    'message': 'Please correct the errors and try again',
                    'errors': form.errors.as_json()
                }, status=400)

        elif action == 'edit_mou':
            form = MOUEditorForm(
                request=request, record=record, data=request.POST
            )

            if form.is_valid():
                record = form.save(request=request, record=record, commit=True)

                data = {
                    'status':'success',
                    'message':'Successfully saved MOU.'
                }
                return JsonResponse(data)
            else:
                return JsonResponse({
                    'message': 'Please correct the errors and try again',
                    'errors': form.errors.as_json()
                }, status=400)
        
        elif action == 'edit_mou_signator':
            form = MOUSignatorForm(
                record=None, data=request.POST
            )

            if form.is_valid():
                record = form.save(request=request, mou=record, commit=True)

                data = {
                    'status':'success',
                    'message':'Successfully saved MOU Signator.',
                    'action': 'reload_table'
                }
                return JsonResponse(data)
            else:
                return JsonResponse({
                    'message': 'Please correct the errors and try again',
                    'errors': form.errors.as_json()
                }, status=400)

    return render(
        request,
        template, {
            'page_title': 'MOU',
            'menu': menu,
            'form': form,
            'signators_api': mark_safe(
                '/ce/highschools/mous/api/mou_signators?format=datatables&mou_id=' + str(record.id)
            ),
            'signatures_api': mark_safe(
                '/ce/highschools/mous/api/mou_signatures?format=datatables&mou_id=' + str(record.id)
            ),
            'log_api': mark_safe(
                '/ce/announcements/api/bulk_message_logs?format=datatables&bulk_message_id=' + str(record.id)
            ),
            'form_signator': form_signator,
            'finalize_form': finalize_form,
            # 'recipient_form': recipient_form,
            'record': record,
            'signator': signator,
            }
        )

@user_passes_test(user_has_cis_role, login_url='/')
def mous(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'highschools', 'mous')

    template = 'mou/mous.html'
    
    return render(
        request,
        template, {
            'page_title': 'MOUs',
            'urls': {
            },
            'menu': menu,
            'add_new_form': MOUInitForm(request)
            }
        )
