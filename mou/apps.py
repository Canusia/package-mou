from django.apps import AppConfig


class MOUConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mou'

    # Settings will go here
    CONFIGURATORS = [
            {
            'app': 'mou',
            'name': 'email_settings',
            'title': 'MOU Notifications',
            'description': '-',
            'categories': [
                '2'
            ]
        },
    ]
    REPORTS = [
        {
            'app': 'mou',
            'name': 'signature_link_export',
            'title': 'MOU Signatures Pending Export',
            'description': 'Export pending signatures for the MOU',
            'categories': [
                'Misc.'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'app': 'mou',
            'name': 'mou_pdf_export',
            'title': 'MOU Signatures Export',
            'description': 'Export MOU signatures to PDF',
            'categories': [
                'Misc.'
            ],
            'available_for': [
                'ce'
            ]
        },
    ]

    def ready(self):
        import mou.signals
           
class DevMOUConfig(AppConfig):
    name = 'mou.mou'
    
    CONFIGURATORS = [
            {
            'app': name,
            'name': 'email_settings',
            'title': 'MOU Notifications',
            'description': '-',
            'categories': [
                '2'
            ]
        },
    ]
    
    REPORTS = [
        {
            'app': 'mou.mou',
            'name': 'signature_link_export',
            'title': 'MOU Signatures Pending Export',
            'description': 'Export pending signatures for the MOU',
            'categories': [
                'Misc.'
            ],
            'available_for': [
                'ce'
            ]
        },
        {
            'app': 'mou.mou',
            'name': 'mou_pdf_export',
            'title': 'MOU Signatures Export',
            'description': 'Export MOU signatures to PDF',
            'categories': [
                'Misc.'
            ],
            'available_for': [
                'ce'
            ]
        },
    ]

    def ready(self):
        import mou.mou.signals