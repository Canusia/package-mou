from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import *  # Import all models from the app


class MOUAdmin(admin.ModelAdmin):
    model = MOU

class MOUNoteAdmin(admin.ModelAdmin):
    model = MOUNote

class MOUSignatorAdmin(admin.ModelAdmin):
    model = MOUSignator

class MOUSignatureAdmin(admin.ModelAdmin):
    model = MOUSignature

admin.site.register(MOU, MOUAdmin)
admin.site.register(MOUNote, MOUNoteAdmin)
admin.site.register(MOUSignator, MOUSignatorAdmin)
admin.site.register(MOUSignature, MOUSignatureAdmin)
