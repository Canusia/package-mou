import uuid, datetime

from django.http import HttpResponse

from django.utils import timezone
from django.db import models
from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models import JSONField
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from cron_validator import CronValidator
from mailer import send_mail, send_html_mail
from model_utils import FieldTracker

from cis.utils import getDomain
from cis.storage_backend import PrivateMediaStorage

from cis.models.note import Note
from cis.models.customuser import CustomUser

from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSPosition, HSAdministratorPosition
from cis.models.district import DistrictPosition, DistrictAdministratorPosition

from .settings.email_settings import email_settings as configs

class MOU(models.Model):
    """
    Speaker model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=100)

    created_on = models.DateTimeField(verbose_name="Created On", auto_now_add=True)

    created_by = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.PROTECT,
        verbose_name='Created By'
    )

    GROUP_BY_CHOICES = [
        ('highschool', 'School')
    ]
    group_by = models.CharField(
        choices=GROUP_BY_CHOICES,
        default='highschool',
        max_length=50
    )

    send_on_after = models.DateTimeField(blank=True, null=True)
    send_until = models.DateTimeField(blank=True, null=True)
    
    cron = models.CharField(max_length=100)
    
    academic_year = models.ForeignKey(
        'cis.AcademicYear',
        on_delete=models.PROTECT,
        verbose_name='Academic Year'
    )
    
    description = models.TextField(
        blank=True,
        null=True
    )

    mou_text = models.TextField(
        blank=True,
        null=True
    )

    STATUS_OPTIONS = [
        # ('', 'Select'),
        ('draft', 'Draft'),
        ('ready', 'Ready to Send'),
    ]
    status = models.CharField(
        max_length=10,
        verbose_name='Status',
        choices=STATUS_OPTIONS,
        default='draft',
        blank=True,
        null=True
    )

    tracker = FieldTracker(fields=['status'])

    meta = JSONField(
        default=dict,
        blank=True,
        null=True
    )

    def __str__(self):
        return self.title
    
    class Meta:
        ordering = ['-academic_year', 'title']


    def should_message_be_sent(self):
        if self.status != 'ready':
            return False

        cron_scheduler_start_time = datetime.datetime.now().replace(
            microsecond=0,
            second=0
        )

        cron_scheduler_end_time = cron_scheduler_start_time + datetime.timedelta(
            minutes=getattr(settings, 'MYCE_CRON_INTERVAL')
        )

        executors = CronValidator.get_execution_time(
            self.cron,
            from_dt=cron_scheduler_start_time,
            to_dt=cron_scheduler_end_time
        )
        
        if executors:
            for executor in executors:
                return True
        return False

    def can_edit(self):
        return True
        return False if self.status == 'ready' else True
    
    @property
    def poc(self):
        template = 'mou/templates/poc.html'

        return render_to_string(template, {
            'name': self.meta.get('poc_name'),
            'email': self.meta.get('poc_email'),
            'phone': self.meta.get('poc_phone'),
        })
    
    @property
    def source_of_funds(self):
        template = 'mou/templates/source_of_funds.html'

        return render_to_string(template, {
            'parent_pay': 'x' if self.meta.get('source_of_funds') == 'parent_pay' else '',
            'split_pay': 'x' if self.meta.get('source_of_funds') == 'split_pay' else '',
            'school_pay': 'x' if self.meta.get('source_of_funds') == 'school_pay' else '',
            'other': 'x' if self.meta.get('source_of_funds') == 'other' else '',
            'parent_pay_percentage': self.meta.get('parent_pay_percentage') if self.meta.get('parent_pay_percentage') != None else '',
            'school_pay_percentage': self.meta.get('school_pay_percentage') if self.meta.get('school_pay_percentage') != None else '',
            'other_pay': self.meta.get('other_pay', ''),
        })

    @property
    def tuition_manager(self):
        template = 'mou/templates/poc.html'

        return render_to_string(template, {
            'name': self.meta.get('tuition_manager_name'),
            'email': self.meta.get('tuition_manager_email'),
            'phone': self.meta.get('tuition_manager_phone'),
        })
    
    # def signature_asHTML(self, weight=1):
    #     signature = MOUSignature.objects.filter(
    #         signator_template__mou=self,
    #         signator_template__weight=weight,
    #         # highschool=self.highschool,
    #         status='signed'
    #     )

    #     if not signature.exists():
    #         return ' '
    #     return signature[0]._signature
    
    @property
    def sexy_status(self):
        for k, v in self.STATUS_OPTIONS:
            if k == self.status:
                return v
        return '-'

    def initialize_signature_status(self):    
        pending_signatures = MOUSignature.objects.filter(
            signator_template__mou=self,
            status__in=['', 'pending']
        ).order_by(
            'highschool__name',
            'signator_template__weight'
        ).distinct(
            'highschool__name'
        )

        for pending in pending_signatures:
            pending.mark_as_pending()

        return pending_signatures.count()
    
    def initialize_signatures(self):
        if self.can_edit():
            return (False, 'MOU is not finalized')
        
        highschools = HighSchool.objects.filter(status__iexact='active')

        signators = MOUSignator.objects.filter(
            mou=self
        ).order_by('weight')

        result = {}
        for highschool in highschools:
            result[highschool.code] = {
                'signator': []
            }

            for signator in signators:

                if signator.role_type == 'highschool_admin':
                    # get the active person 
                    admin_positions = HSAdministratorPosition.objects.filter(
                        position__id=signator.role,
                        highschool=highschool,
                        status__iexact='active'
                    )
                else:
                    admin_positions = DistrictAdministratorPosition.objects.filter(
                        position__id=signator.role,
                        district=highschool.district,
                        status__iexact='active'
                    )

                if not admin_positions:
                    result[highschool.code]['signator'].append({
                        signator.role_type: f'Not found for {signator.weight}'
                    })
                else:
                    if MOUSignature.objects.filter(
                        highschool=highschool,
                        signator=admin_positions[0].hsadmin.user,
                        signator_template=signator
                    ).exists():
                        result[highschool.code]['signator'].append({
                            signator.role_type: str(admin_positions[0].hsadmin.user) + ' exists'
                        })
                    else:
                        signature = MOUSignature(
                            highschool=highschool,
                            signator=admin_positions[0].hsadmin.user,
                            signator_template=signator,
                            status=''
                        )

                        signature.save()
                        result[highschool.code]['signator'].append({
                            signator.role_type: str(admin_positions[0].hsadmin.user) + ' added'
                        })

        return result
                    
    @property
    def ce_url(self):
        return reverse_lazy(
            'mou_ce:mou',
            kwargs={
                'record_id': self.id
            }
        )
    
    def as_pdf(self):
        ...

    def add_note(self, createdby=None, note='', meta=None):

        if not createdby:
            createdby = CustomUser.objects.get(
                username='cron'
            )

        note = MOUNote(
            createdby=createdby,
            note=note,
            student=self
        )

        if not meta:
            meta = {'type': 'private'}

        note.meta = meta
        note.save()

        return note
    
class MOUNote(Note, models.Model):
    """
    Notes for Class Section
    """
    meo = models.ForeignKey(
        'mou.MOU',
        on_delete=models.PROTECT,
        blank=True,
        null=True
    )

    meta = JSONField(blank=True, null=True)
    class Meta:
        ordering = ['createdon']

    @property
    def sexy_note(self):
        return mark_safe(self.note)


class MOUSignator(models.Model):
    """
    Speaker model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    created_on = models.DateTimeField(verbose_name="Created On", auto_now_add=True, editable=False)

    created_by = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.PROTECT,
        verbose_name='Created By'
    )
    mou = models.ForeignKey(
        'mou.MOU',
        on_delete=models.PROTECT,
        verbose_name='Created By'
    )

    weight = models.SmallIntegerField(verbose_name="Weight", default=1)
    ROLE_TYPES = [
        ('highschool_admin', "School Administrator"),
        ('district_admin', "District Administrator"),
    ]
    role_type = models.CharField(
        max_length=100,
        verbose_name='Role Type',
        choices=ROLE_TYPES,
        default='highschool_admin'
    )

    # This will be principal, vice-principal, superintendent etc
    role = models.UUIDField(
        max_length=100,
        verbose_name='Role'
    )

    meta = JSONField(blank=True, null=True)

    @property
    def complete_extra_form(self):
        return 'Yes' if self.meta.get('complete_extra_form') == '1' else 'No'
    

    @property
    def sexy_role(self):
        if self.role_type == 'highschool_admin':
            try:
                return HSPosition.objects.get(pk=self.role).name
            except:
                return 'HS Position Not Found'
        elif self.role_type == 'district_admin':
            try:
                return DistrictPosition.objects.get(pk=self.role).name
            except:
                return 'District Position Not Found'

class MOUSignature(models.Model):
    """
    Speaker model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    created_on = models.DateTimeField(verbose_name="Created On", auto_now_add=True, editable=False)

    highschool = models.ForeignKey(
        'cis.HighSchool',
        on_delete=models.PROTECT,
        verbose_name='School'
    )

    signator = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.PROTECT,
        verbose_name='Signator'
    )
    
    signator_template = models.ForeignKey(
        'mou.MOUSignator',
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        verbose_name='Signator Templates'
    )

    STATUS_OPTIONS = [
        ('', 'Not Ready To Sign'),
        ('pending', 'Pending Signature'),
        ('signed', 'Signed'),
    ]
    status = models.CharField(
        max_length=10,
        verbose_name='Status',
        choices=STATUS_OPTIONS,
        blank=True,
        null=True
    )

    meta = JSONField(
        default=dict,
        blank=True,
        null=True
    )

    tracker = FieldTracker(fields=['status'])

    class Meta:
        unique_together = ['highschool', 'signator', 'signator_template']

    @property
    def sexy_status(self):
        for k, v in self.STATUS_OPTIONS:
            if k == self.status:
                return v
        return 'N/A'
    
    def signature_asHTML(self, weight=1):
        
        signature = MOUSignature.objects.filter(
            signator_template__mou=self.signator_template.mou,
            signator_template__weight=weight,
            highschool=self.highschool,
            status='signed'
        )
        
        if not signature.exists():
            return ' '
        return signature[0]._signature
    
    def send_notification(self):
        
        notif_settings = configs.from_db()

        if self.status == 'pending':
            email_template = Template(notif_settings.get('email_message', 'change me'))
            subject = notif_settings.get('email_subject')
        elif self.status == 'signed':
            email_template = Template(notif_settings.get('signed_email_message', 'change me'))
            subject = notif_settings.get('signed_email_subject')

        context = Context({
            'highschool_name': self.highschool.name,
            'signator_firstname': self.signator.first_name,
            'signator_lastname': self.signator.last_name,
            'mou_title': self.mou_title,
            'signature_url': self.signature_url,
            'mou_download_link': self.as_pdf_url,
        })
        text_body = email_template.render(context)
        to = [self.signator.email]

        if getattr(settings, 'DEBUG', True):
            to = notif_settings.get('notify_address', 'kadaji@gmail.com').split(',')

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

    def is_ready_to_be_signed(self):
        return True if self.status == 'pending' else False
    
    def mark_as_pending(self):
        self.status = 'pending'
        self.save()
    
    def mark_as_signed(self, commit=True):
        self.status = 'signed'

        if commit:
            self.save()
        return self
    

    def download_as_pdf(self, download=True):
        import pdfkit, datetime
    
        base_template = 'mou/templates/mou.html'
        template = get_template(base_template)

        html = template.render({
            'generated_on': datetime.datetime.now(),
            'mou_text': self.mou_text,
            'record': self,
        })
        
        options = {
            'page-size': 'Letter'
        }
        pdf = pdfkit.from_string(html, False, options)

        if download:
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="mou_"' + str(self.id) + ".pdf"

            return response
        return pdf
    
    @property
    def teacher_list(self):
        from cis.models.teacher import TeacherCourseCertificate
        from .settings.email_settings import email_settings as configurator

        configs = configurator.from_db()

        teacher_certs = TeacherCourseCertificate.objects.filter(
            teacher_highschool__highschool=self.highschool
        )

        if configs.get('teacher_course_status'):
            teacher_certs = teacher_certs.filter(
                status__in=configs.get('teacher_course_status')
            )
        
        template = 'mou/templates/teacher_list.html'

        return render_to_string(template, {
            'teachers': teacher_certs
        })
    
    @property
    def class_section_list(self):
        from cis.models.section import ClassSection

        teacher_certs = TeacherCourseCertificate.objects.filter(
            teacher_highschool__highschool=self.highschool
        )
        
        template = 'mou/templates/teacher_list.html'

        return render_to_string(template, {
            'teachers': teacher_certs
        })


    @property
    def mou_text(self):
        # This needs to be updated so all shortcodes are applied

        mou = Template(self.signator_template.mou.mou_text)
        context = Context({
            # 'poc_information': self.signator_template.mou.poc,
            # 'tuition_manager_information': self.signator_template.mou.tuition_manager,
            # 'source_of_funds_information': self.signator_template.mou.source_of_funds,
            'highschool_name': self.highschool.name,
            'highschool_ceeb': self.highschool.code,
            'teacher_list': self.teacher_list,
            'academic_year': self.signator_template.mou.academic_year.name,
            'signature_1': self.signature_asHTML(1),
            'signature_2': self.signature_asHTML(2),
            'signature_3': self.signature_asHTML(3),
        })

        mou_text = mou.render(context)
        return mou_text
    
    @property
    def mou_title(self):
        return self.signator_template.mou.title
    
    
    @property
    def _signature(self):
        template = 'mou/templates/signature.html'

        if self.meta.get('signature', '').startswith('Marked'):
            signature = 'Marked as Signed'
        else:
            signature = mark_safe(
                f"<img class='responsive' src='{self.meta['signature']}' />"
            )

        return render_to_string(template, {
            'name': f'{self.signator.first_name} {self.signator.last_name}',
            'email': self.signator.email,
            'role': self.signator_template.sexy_role,
            'signature': signature,
            'date': self.meta.get('signed_on')
        })


    def next_signator(self):
        
        next_signator = MOUSignature.objects.filter(
            highschool=self.highschool,
            signator_template__mou=self.signator_template.mou,
            signator_template__weight__gt=self.signator_template.weight
        )

        if next_signator.exists():
            next_signator = next_signator[0]

            if next_signator.status == '':
                next_signator.mark_as_pending()

                return next_signator
        else:
            return None

    @property
    def signature_url(self):
        from cis.utils import getDomain
        return getDomain() + str(
            reverse_lazy(
                'mou:sign',
                kwargs={
                    'signature_id': self.id
                }
            )
        )
    
    @property
    def as_pdf_url(self):
        from cis.utils import getDomain
        return getDomain() + str(
            reverse_lazy(
                'mou:signature_as_PDF',
                kwargs={
                    'signature_id': self.id
                }
            )
        )
