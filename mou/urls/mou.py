"""
    Important Link CE URL Configuration
"""
from django.urls import path, include
from rest_framework import routers

from ..views import (
    sign_mou,
    mou_signature_asPDF
)

app_name = 'mou'

urlpatterns = [
    path('sign_mou/<uuid:signature_id>', sign_mou, name='sign'),
    path('mou_signature_as_pdf/<uuid:signature_id>', mou_signature_asPDF, name='signature_as_PDF')
]
