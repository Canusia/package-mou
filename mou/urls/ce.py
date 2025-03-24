"""
    Important Link CE URL Configuration
"""
from django.urls import path, include
from rest_framework import routers

from ..views import (
    mous,
    mou, 
    # add_new, delete,
    mou_delete,
    mou_add_new,
    do_bulk_action,
    MOUViewSet,
    MOUSignatorViewSet,
    MOUSignatureViewSet
)

app_name = 'mou_ce'

router = routers.DefaultRouter()
router.register('mous', MOUViewSet, basename=app_name)
router.register('mou_signators', MOUSignatorViewSet, basename=app_name)
router.register('mou_signatures', MOUSignatureViewSet, basename=app_name)

urlpatterns = [
    path('', mous, name='all'),

    path('mou/add_new', mou_add_new, name='mou_add_new'),
    path('mou/<uuid:record_id>', mou, name='mou'),
    path('mou/delete/<uuid:record_id>', mou_delete, name='mou_delete'),
    path('mou/do_bulk_action', do_bulk_action, name='bulk_action'),
    
    # path('bulk_message/get_datasource_filters', bulk_message_get_datasource_filters, name='get_datasource_filters'),
    # path('bulk_message/preview/<uuid:record_id>', bulk_message_preview, name='bulk_message_preview'),
    # path('bulk_message/delete/<uuid:record_id>', bulk_message_delete, name='bulk_message_delete'),
    # path('bulk_message/delete_all_recipients/<uuid:record_id>', bulk_message_delete_all_recipients, name='bulk_message_delete_all_recipients'),

    path('api/', include(router.urls)),
]
