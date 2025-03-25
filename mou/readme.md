- Register app in INSTALLED_APPS
    'mou.apps.MOUConfig'

- add urls
    - In myce.urls 
        - path('mou/', include('mou.urls.mou')),
        - path('ce/highschools/mous/', include('mou.urls.ce')),

- add static_dir
    os.path.join(get_package_path("mou"), 'staticfiles'),

- add send_mou_emails to cron_jobs.py