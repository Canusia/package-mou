from django.urls import path

from ..views_hs_admin import signed_mous

app_name = 'mou_hs'

urlpatterns = [
    path('', signed_mous, name='signed_mous'),
]
