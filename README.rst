MyCE - MOUs
====================

- Setup

In settings.py, add the app to INSTALLED_APPS as 
'mou.apps.MOUConfig'

In myce.urls.py
- path('ce/mou/', include('mou.urls.ce')),

In Settings -> Misc -> Menu add the following
{
    "label":"MOUs",
    "name":"mous",
    "url":"mou_ce:all"
},