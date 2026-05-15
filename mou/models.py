import copy
import re
import uuid, datetime

from django.http import HttpResponse

from django.utils import timezone
from django.db import models, transaction
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

    manager = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='managed_mous',
        verbose_name='MOU Manager',
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


    def should_message_be_sent(self, now=None):
        if self.status != 'ready':
            return False

        if now is None:
            now = datetime.datetime.now()
        cron_scheduler_start_time = now.replace(
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

    def duplicate(self, created_by):
        """Create a fresh draft copy of this MOU and its signator chain.

        Copies MOU fields and every MOUSignator row, repointed at the new
        MOU. Does NOT copy MOUSignature records or attached highschools —
        the copy starts with no schools and status 'draft'.
        """
        with transaction.atomic():
            new_mou = MOU.objects.create(
                title=('Copy of ' + self.title)[:100],
                group_by=self.group_by,
                cron=self.cron,
                academic_year=self.academic_year,
                description=self.description,
                mou_text=self.mou_text,
                meta=copy.deepcopy(self.meta) if self.meta else {},
                status='draft',
                created_by=created_by,
            )
            for sig in MOUSignator.objects.filter(mou=self).order_by('weight'):
                MOUSignator.objects.create(
                    mou=new_mou,
                    created_by=created_by,
                    weight=sig.weight,
                    role_type=sig.role_type,
                    role=sig.role,
                    meta=copy.deepcopy(sig.meta) if sig.meta else None,
                )
        return new_mou

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
        ('college_admin', "College Administrator"),
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
        elif self.role_type == 'college_admin':
            return 'College Administrator'
            
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

    STATUS_PENDING = 'pending'
    STATUS_CHANGES_REQUESTED = 'changes_requested'
    STATUS_OPTIONS = [
        ('', 'Not Ready To Sign'),
        ('pending', 'Pending Signature'),
        ('changes_requested', 'Changes Requested'),
        ('signed', 'Signed'),
    ]
    status = models.CharField(
        max_length=20,
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
            return mark_safe('<em class="text-muted">Not yet signed</em>')
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
            'role': self.meta.get('role') if self.meta.get('role') else 'N/A',
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

    def send_change_request_notification(self):
        notif_settings = configs.from_db()

        subject = notif_settings.get('change_request_email_subject', 'MOU Change Request')
        body_raw = notif_settings.get('change_request_email_message', '')
        if not body_raw:
            return  # nothing configured; skip silently

        mou = self.signator_template.mou
        if mou.manager and mou.manager.email:
            to = [mou.manager.email]
        else:
            fallback = notif_settings.get('notify_address') or ''
            to = [addr.strip() for addr in fallback.split(',') if addr.strip()]

        if not to:
            return

        if getattr(settings, 'DEBUG', True):
            fallback = notif_settings.get('notify_address') or ''
            debug_to = [addr.strip() for addr in fallback.split(',') if addr.strip()]
            if debug_to:
                to = debug_to

        context = Context({
            'highschool_name': self.highschool.name,
            'signator_firstname': self.signator.first_name,
            'signator_lastname': self.signator.last_name,
            'mou_title': self.mou_title,
            'comment': self.meta.get('change_request_comment', ''),
            'mou_url': getDomain() + str(mou.ce_url),
            'signature_url': self.signature_url,
        })
        text_body = Template(body_raw).render(context)
        html_body = get_template('cis/email.html').render({'message': text_body})

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to,
        )

    def is_ready_to_be_signed(self):
        return True if self.status == 'pending' else False
    
    @property
    def is_signed(self):
        return True if self.status == 'signed' else False
    
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
    
        from .settings.email_settings import email_settings as configurator

        base_template = 'mou/templates/mou.html'
        template = get_template(base_template)

        html = template.render({
            'generated_on': datetime.datetime.now(),
            'mou_text': self.mou_text,
            'record': self,
            'custom_css': configurator.from_db().get('custom_css', ''),
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
    def mou_pdf_url(self):
        return reverse_lazy(
            'mou:signature_as_PDF',
            kwargs={
                'signature_id': self.id
            }
        )
    
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
    def role(self):
        return self.meta.get('role')
    
    @property
    def choice_teacher_list(self):
        from cis.models.teacher import TeacherCourseCertificate
        from .settings.email_settings import email_settings as configurator

        configs = configurator.from_db()

        teacher_certs = TeacherCourseCertificate.objects.filter(
            teacher_highschool__highschool=self.highschool
        ).exclude(
            course__stream__contains='pathways'
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
    def pathways_course_list(self):
        from cis.models.future_sections import FutureSection, FutureCourse
        from cis.models.course import Course
        from cis.settings.future_sections import future_sections as       configurator

        configs = configurator.from_db()
        future_sections = FutureCourse.objects.filter(
            teacher_course__teacher_highschool__highschool=self.highschool,
            academic_year=self.signator_template.mou.academic_year,
            teacher_course__course__stream__contains='pathways',
            section_info__teaching='yes'
        ).order_by(
            'teacher_course__course__name'
        )

        template = 'mou/templates/future_section_courses.html'

        return render_to_string(template, {
            'courses': future_sections
        })
    
    @property
    def choice_course_list(self):
        from cis.models.future_sections import FutureSection, FutureCourse
        from cis.models.course import Course
        from cis.settings.future_sections import future_sections as       configurator

        configs = configurator.from_db()
        future_sections = FutureCourse.objects.filter(
            teacher_course__teacher_highschool__highschool=self.highschool,
            academic_year=self.signator_template.mou.academic_year,
            section_info__teaching='yes',
            teacher_course__course__stream__contains='cccl'
        ).order_by(
            'teacher_course__course__name'
        )

        template = 'mou/templates/future_section_courses.html'

        return render_to_string(template, {
            'courses': future_sections
        })
    
    @property
    def facilitator_course_list(self):
        from cis.models.future_sections import FutureSection, FutureCourse
        from cis.models.course import Course
        from cis.settings.future_sections import future_sections as       configurator

        configs = configurator.from_db()
        future_sections = FutureCourse.objects.filter(
            teacher_course__teacher_highschool__highschool=self.highschool,
            academic_year=self.signator_template.mou.academic_year,
            teacher_course__course__stream__contains='dual_enrollment',
            section_info__teaching='yes'
        ).order_by(
            'teacher_course__course__name'
        )

        template = 'mou/templates/future_section_courses.html'

        return render_to_string(template, {
            'courses': future_sections
        })
    
    @property
    def course_list(self):
        from cis.models.future_sections import FutureSection, FutureCourse
        from cis.models.course import Course

        future_sections = FutureCourse.objects.filter(
            teacher_course__teacher_highschool__highschool=self.highschool,
            academic_year=self.signator_template.mou.academic_year,
            section_info__teaching='yes'
        ).order_by(
            'teacher_course__course__name'
        )

        template = 'mou/templates/future_section_courses.html'

        return render_to_string(template, {
            'courses': future_sections
        })

    @property
    def future_course_list(self):
        import importlib.util
        if importlib.util.find_spec('future_sections.future_sections'):
            from future_sections.future_sections.models import FutureCourse
        else:
            from future_sections.models import FutureCourse
        from .settings.email_settings import email_settings

        future_sections = FutureCourse.objects.filter(
            teacher_course__teacher_highschool__highschool=self.highschool,
            academic_year=self.signator_template.mou.academic_year
        ).order_by(
            'teacher_course__course__name'
        )

        # If the admin configured a custom HTML template for this shortcode,
        # render it as an inline Django template; otherwise fall back to the
        # bundled file.
        custom_html = (email_settings.from_db().get('future_course_list_template') or '').strip()
        if custom_html:
            return Template(custom_html).render(Context({'courses': future_sections}))

        template = 'mou/templates/future_section_courses.html'
        return render_to_string(template, {
            'courses': future_sections
        })
    
    @property
    def pathways_teacher_list(self):
        from cis.models.teacher import TeacherCourseCertificate
        from .settings.email_settings import email_settings as configurator

        configs = configurator.from_db()

        teacher_certs = TeacherCourseCertificate.objects.filter(
            teacher_highschool__highschool=self.highschool,
            course__stream__contains='pathways'
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
        from cis.models.teacher import TeacherCourseCertificate

        teacher_certs = TeacherCourseCertificate.objects.filter(
            teacher_highschool__highschool=self.highschool
        )
        
        template = 'mou/templates/teacher_list.html'

        return render_to_string(template, {
            'teachers': teacher_certs
        })


    # {{role_<attr>_<Position_Name_With_Underscores>}}
    # <attr>      ∈ {first_name, last_name, email, name}  (name = "First Last")
    # underscores in <Position_Name> are translated to spaces for the lookup
    # (case-insensitive on HSPosition.name). Empty string if no admin holds that
    # position at this MOU's highschool.
    # Disambiguation: attr is bounded by the alternation, so the rest of the
    # token (after `role_<attr>_`) is the position name even though it contains
    # underscores. Examples:
    #   {{role_first_name_Academic_Principal}}  -> first name of the "Academic Principal"
    #   {{role_last_name_Dean_of_Guidance}}     -> last name of the "Dean of Guidance"
    #   {{role_email_Principal}}                 -> email of the "Principal"
    _ROLE_SHORTCODE_RE = re.compile(
        r'\{\{\s*role_(first_name|last_name|email|name)_([A-Za-z0-9_]+?)\s*\}\}'
    )

    def _resolve_role_shortcode(self, attr, position_token):
        from cis.models.highschool_administrator import HSAdministratorPosition

        position_name = position_token.replace('_', ' ')
        admin_position = HSAdministratorPosition.objects.filter(
            highschool=self.highschool,
            position__name__iexact=position_name,
        ).select_related('hsadmin__user').first()
        if not admin_position:
            return ''

        user = admin_position.hsadmin.user
        if attr == 'name':
            return f'{user.first_name} {user.last_name}'.strip()
        return getattr(user, attr, '') or ''

    def _render_role_shortcodes(self, text):
        return self._ROLE_SHORTCODE_RE.sub(
            lambda m: self._resolve_role_shortcode(m.group(1), m.group(2)),
            text,
        )

    @property
    def mou_text(self):
        from .settings.email_settings import email_settings, AVAILABLE_SHORTCODES

        cfg = email_settings.from_db()
        configured = cfg.get('available_shortcodes')
        if configured is None:
            # Setting not yet saved → backwards-compat: all shortcodes allowed.
            allowed = {k for k, _ in AVAILABLE_SHORTCODES}
        else:
            allowed = set(configured)

        choice_keys = {k for k, _ in AVAILABLE_SHORTCODES}

        raw_text = self.signator_template.mou.mou_text
        # role_* shortcodes are preprocessed before Django Template rendering
        # because Django can't resolve dynamic variable names. If 'role_lookup'
        # is disabled, leave the {{role_*}} tokens untouched — Django will
        # render them as empty strings since they're not in the context.
        if 'role_lookup' in allowed:
            raw_text = self._render_role_shortcodes(raw_text)

        # Full set of shortcode values. Anything NOT in `choice_keys` (e.g. the
        # historical `course_list`) is always rendered with its real value to
        # preserve backwards compatibility with existing MOU templates. Keys in
        # `choice_keys` but absent from `allowed` are forced to empty string.
        # Shortcodes whose values are HTML and must not be auto-escaped by the
        # Django template engine when rendered into mou_text.
        HTML_SHORTCODES = {
            'signature_1', 'signature_2', 'signature_3', 'signature_4',
            'teacher_list', 'choice_teacher_list', 'pathways_teacher_list',
            'pathways_course_list', 'choice_course_list',
            'facilitator_course_list', 'course_list', 'future_course_list',
        }

        full_values = {
            'signature_1':             self.signature_asHTML(1),
            'signature_2':             self.signature_asHTML(2),
            'signature_3':             self.signature_asHTML(3),
            'signature_4':             self.signature_asHTML(4),
            'highschool_name':         self.highschool.name,
            'highschool_ceeb':         self.highschool.code,
            'highschool_address1':     self.highschool.address1 or '',
            'highschool_city':         self.highschool.city or '',
            'highschool_state':        self.highschool.state or '',
            'highschool_zip':          self.highschool.postal_code or '',
            'academic_year':           self.signator_template.mou.academic_year.name,
            'teacher_list':            self.teacher_list,
            'choice_teacher_list':     self.choice_teacher_list,
            'pathways_teacher_list':   self.pathways_teacher_list,
            'pathways_course_list':    self.pathways_course_list,
            'choice_course_list':      self.choice_course_list,
            'facilitator_course_list': self.facilitator_course_list,
            'course_list':             self.course_list,
            'future_course_list':      self.future_course_list,
        }

        def _resolve(key, value):
            if key in choice_keys and key not in allowed:
                return ''
            if key in HTML_SHORTCODES:
                return mark_safe(value or '')
            return value

        context = Context({k: _resolve(k, v) for k, v in full_values.items()})

        return Template(raw_text).render(context)
    
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
