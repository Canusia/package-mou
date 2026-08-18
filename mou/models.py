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
        """Mark the current unsigned person at each school as Next Up.

        Next Up means it is their turn; it is not an email. Pending is set
        only after send_notification actually sends.
        """
        count = 0
        for sig in self.current_unsigned_signatures():
            if sig.status in ('', None):
                sig.mark_as_next()
                count += 1
        return count

    def current_unsigned_signatures(self):
        """The signer whose turn it is at each school, or nothing when blocked.

        Only `signed` is excluded when finding each school's lowest-weight
        outstanding row: excluding `changes_requested` too would let the search
        skip *past* an open change request and promote a later signer, which
        contradicts MOUSignature.is_next_in_chain() and let signers sign out of
        order. A school whose lowest outstanding row is `changes_requested` is
        blocked until CE resolves it, so it yields nothing at all.
        """
        lowest_per_school = MOUSignature.objects.filter(
            signator_template__mou=self,
        ).exclude(
            status='signed',
        ).order_by(
            'highschool__name',
            'signator_template__weight',
        ).distinct(
            'highschool__name'
        )
        # Materialised deliberately: DISTINCT ON cannot be composed with a
        # further .exclude() in one queryset, and this is one row per school.
        blocked = MOUSignature.STATUS_CHANGES_REQUESTED
        ids = [sig.pk for sig in lowest_per_school if sig.status != blocked]
        return MOUSignature.objects.filter(pk__in=ids).order_by(
            'highschool__name',
            'signator_template__weight',
        )

    def open_change_requests(self):
        """Signatures waiting on CE to review a signer's requested edits."""
        return MOUSignature.objects.filter(
            signator_template__mou=self,
            status='changes_requested',
        ).select_related(
            'highschool',
            'signator',
            'signator_template',
        ).order_by(
            '-created_on',
        )
    
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
                    college_user=sig.college_user,
                    title=sig.title,
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

    # College signers are named people (same on every school's copy), not a
    # HS/district position UUID. Stored on the row so weight is not hard-wired
    # to college_administrator_1/2 in settings.
    college_user = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name='mou_college_signator_roles',
        verbose_name='College Signer',
    )
    title = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='Signer Title',
        help_text='Shown on the signature block. Used for college administrators; school/district rows still resolve the position name.',
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
            return self.title or 'College Administrator'
            
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
    STATUS_NEXT = 'next'
    STATUS_CHANGES_REQUESTED = 'changes_requested'
    STATUS_OPTIONS = [
        ('', 'Not Ready To Sign'),
        ('next', 'Next Up'),
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

    @property
    def notified_on_display(self):
        """When the last please-sign / reminder email went out (empty if never)."""
        return (self.meta or {}).get('notified_on') or ''

    @property
    def change_request_comment(self):
        return (self.meta or {}).get('change_request_comment') or ''

    @property
    def change_requested_on(self):
        return (self.meta or {}).get('change_requested_on') or ''
    
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
        from .settings.helpers import notification_recipients

        notif_settings = configs.from_db()
        please_sign_statuses = ('', None, 'next', 'pending')

        if self.status in please_sign_statuses:
            # First send uses the request copy; later sends (cron / Send
            # Signature Link again) use reminder_* when set. Status stays
            # blank / Next Up until this send succeeds — pending means emailed.
            count = 0
            if self.meta:
                try:
                    count = int(self.meta.get('notification_count') or 0)
                except (TypeError, ValueError):
                    count = 0
            use_reminder = count >= 1
            if use_reminder and (notif_settings.get('reminder_email_message') or '').strip():
                body_raw = notif_settings.get('reminder_email_message')
                subject = (
                    notif_settings.get('reminder_email_subject')
                    or notif_settings.get('email_subject')
                )
            else:
                body_raw = notif_settings.get('email_message', 'change me')
                subject = notif_settings.get('email_subject')
            email_template = Template(body_raw)
        elif self.status == 'signed':
            email_template = Template(notif_settings.get('signed_email_message', 'change me'))
            subject = notif_settings.get('signed_email_subject')
        else:
            return

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
        to = notification_recipients([self.signator.email], notif_settings)
        if not to:
            return

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

        if self.status in please_sign_statuses:
            meta = dict(self.meta or {})
            stamp = timezone.localtime(timezone.now()).strftime('%m/%d/%Y %I:%M %p')
            meta['notification_count'] = count + 1
            meta['notified_on'] = stamp
            self.meta = meta
            self.status = 'pending'
            self.save(update_fields=['status', 'meta'])
            # First please-sign email for this school also notifies later
            # signers once, without a signing link.
            if count == 0:
                self.send_heads_up_to_later_signers(notif_settings)

    def send_heads_up_to_later_signers(self, notif_settings=None):
        """One-time FYI to later signers when this school's first request goes out.

        Called from send_notification after the first pending send succeeds.
        Skips the current signer, anyone already asked to sign, and college
        staff when that setting is off. Does not include a signing URL.
        """
        from .settings.helpers import (
            heads_up_email_enabled,
            heads_up_include_college,
            notification_recipients,
        )

        cfg = notif_settings if notif_settings is not None else configs.from_db()
        if not heads_up_email_enabled(cfg):
            return
        body_raw = (cfg.get('heads_up_email_message') or '').strip()
        subject = (cfg.get('heads_up_email_subject') or '').strip()
        if not body_raw or not subject:
            return

        include_college = heads_up_include_college(cfg)
        later = MOUSignature.objects.filter(
            highschool=self.highschool,
            signator_template__mou=self.signator_template.mou,
            signator_template__weight__gt=self.signator_template.weight,
        ).exclude(
            pk=self.pk,
        ).exclude(
            status='signed',
        ).select_related(
            'signator',
            'signator_template',
            'signator_template__mou',
            'signator_template__mou__academic_year',
            'highschool',
        )

        academic_year = ''
        mou = self.signator_template.mou
        if mou.academic_year_id:
            academic_year = str(mou.academic_year)

        for signature in later:
            if signature.status in (
                MOUSignature.STATUS_PENDING,
                MOUSignature.STATUS_CHANGES_REQUESTED,
            ):
                continue
            if not include_college and signature.signator_template.role_type == 'college_admin':
                continue
            meta = signature.meta or {}
            if meta.get('heads_up_sent'):
                continue

            to = notification_recipients([signature.signator.email], cfg)
            if not to:
                continue

            role = 'N/A'
            if meta.get('role'):
                role = meta['role']
            elif signature.signator_template:
                role = signature.signator_template.sexy_role or 'N/A'

            # No signature_url here on purpose — this is a heads-up, not a request.
            context = Context({
                'highschool_name': signature.highschool.name,
                'signator_firstname': signature.signator.first_name,
                'signator_lastname': signature.signator.last_name,
                'mou_title': signature.mou_title,
                'role': role,
                'academic_year': academic_year,
            })
            text_body = Template(body_raw).render(context)
            html_body = get_template('cis/email.html').render({'message': text_body})
            send_html_mail(
                Template(subject).render(context),
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to,
            )
            meta['heads_up_sent'] = True
            signature.meta = meta
            signature.save(update_fields=['meta'])

    def send_change_request_notification(self):
        from .settings.helpers import notification_recipients, notify_address_list

        notif_settings = configs.from_db()

        subject = notif_settings.get('change_request_email_subject', 'MOU Change Request')
        body_raw = notif_settings.get('change_request_email_message', '')
        if not body_raw:
            return  # nothing configured; skip silently

        mou = self.signator_template.mou
        if mou.manager and mou.manager.email:
            intended = [mou.manager.email]
        else:
            intended = notify_address_list(notif_settings)

        to = notification_recipients(intended, notif_settings)
        if not to:
            return

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

    def mark_as_next(self):
        self.status = self.STATUS_NEXT
        self.save()

    def mark_pending_from_signature_link(self):
        """Get Signature Link asks this person to sign without sending mail.

        Only the current Next Up row flips to pending so later steps cannot
        skip the chain. Does not increment notification_count, so a later
        Send Signature Link still uses the first please-sign copy.
        """
        if self.status in ('signed', self.STATUS_CHANGES_REQUESTED, self.STATUS_PENDING):
            return False
        if self.status != self.STATUS_NEXT and not self.is_next_in_chain():
            return False
        meta = dict(self.meta or {})
        if not meta.get('notified_on'):
            meta['notified_on'] = timezone.localtime(timezone.now()).strftime(
                '%m/%d/%Y %I:%M %p'
            )
        self.meta = meta
        self.status = self.STATUS_PENDING
        self.save(update_fields=['status', 'meta'])
        return True
    
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
    def approved_course_list(self):
        """Distinct certified courses for this school, same status filter as teacher_list.

        Workbook 4.2/4.3: SCCC wants approved courses, not next-year projections
        ({{course_list}} / {{future_course_list}}).
        """
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

        courses = []
        seen = set()
        for cert in teacher_certs.select_related('course').order_by('course__name'):
            course = cert.course
            if not course or course.id in seen:
                continue
            seen.add(course.id)
            courses.append(course)

        return render_to_string('mou/templates/approved_course_list.html', {
            'courses': courses,
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
            'teacher_list', 'choice_teacher_list', 'pathways_teacher_list',
            'pathways_course_list', 'choice_course_list',
            'facilitator_course_list', 'course_list', 'future_course_list',
            'approved_course_list',
        }
        from .settings.helpers import get_max_signator_weight
        max_weight = get_max_signator_weight(cfg)
        for i in range(1, max_weight + 1):
            HTML_SHORTCODES.add(f'signature_{i}')

        district = getattr(self.highschool, 'district', None)

        def _district_attr(name):
            if not district:
                return ''
            return getattr(district, name, None) or ''

        full_values = {
            'highschool_name':         self.highschool.name,
            'highschool_ceeb':         self.highschool.code,
            'highschool_address1':     self.highschool.address1 or '',
            'highschool_city':         self.highschool.city or '',
            'highschool_state':        self.highschool.state or '',
            'highschool_zip':          self.highschool.postal_code or '',
            'district_name':           _district_attr('name'),
            'district_address1':       _district_attr('address1'),
            'district_city':           _district_attr('city'),
            'district_state':          _district_attr('state') or _district_attr('state_code'),
            'district_zip':            _district_attr('postal_code'),
            'academic_year':           self.signator_template.mou.academic_year.name,
            'teacher_list':            self.teacher_list,
            'choice_teacher_list':     self.choice_teacher_list,
            'pathways_teacher_list':   self.pathways_teacher_list,
            'pathways_course_list':    self.pathways_course_list,
            'choice_course_list':      self.choice_course_list,
            'facilitator_course_list': self.facilitator_course_list,
            'course_list':             self.course_list,
            'future_course_list':      self.future_course_list,
            'approved_course_list':    self.approved_course_list,
        }
        for i in range(1, max_weight + 1):
            full_values[f'signature_{i}'] = self.signature_asHTML(i)

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


    def is_next_in_chain(self):
        """True when every earlier signer at this school has already signed."""
        earlier = MOUSignature.objects.filter(
            highschool=self.highschool,
            signator_template__mou=self.signator_template.mou,
            signator_template__weight__lt=self.signator_template.weight,
        ).exclude(status='signed')
        return not earlier.exists()

    def next_signator(self):
        """Promote the next unsigned row to Next Up. Does not email —
        pending is set when send_notification succeeds.
        """
        nxt = MOUSignature.objects.filter(
            highschool=self.highschool,
            signator_template__mou=self.signator_template.mou,
            signator_template__weight__gt=self.signator_template.weight,
        ).exclude(
            status='signed',
        ).order_by(
            'signator_template__weight',
        ).first()
        if nxt and nxt.status in ('', None):
            nxt.mark_as_next()
        return nxt

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
