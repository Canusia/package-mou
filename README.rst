MyCE - MOUs
====================

- Setup

In settings.py, 
    add the app to INSTALLED_APPS as 
        'mou.apps.MOUConfig'

    Add path to STATIC_FILES_DIRS
        os.path.join(get_package_path("mou"), 'staticfiles'),

In myce.urls.py
- path('ce/mou/', include('mou.urls.ce')),

In Settings -> Misc -> Menu add the following
{
    "label":"MOUs",
    "name":"mous",
    "url":"mou_ce:all"
},