from django.contrib.auth import get_user_model
from rest_framework import serializers

from cis.serializers.highschool_admin import CustomUserSerializer
from .models import (
    MOU,
    MOUNote,
    MOUSignator,
    MOUSignature
)


class MOUSerializer(serializers.ModelSerializer):

    ce_url = serializers.CharField(read_only=True)
    sexy_status = serializers.CharField(read_only=True)
    created_on = serializers.DateTimeField(
        format='%Y-%m-%d %I:%M:%S %p'
    )
    # send_on_after = serializers.DateTimeField(
    #     format='%Y-%m-%d %I:%M:%S %p'
    # )

    # send_until = serializers.DateTimeField(
    #     format='%Y-%m-%d %I:%M:%S %p'
    # )

    created_by = CustomUserSerializer()
    
    class Meta:
        model = MOU
        fields = '__all__'

        datatables_always_serialize = [
            'ce_url',
            'sexy_status'
        ]

class MOUSignatorSerializer(serializers.ModelSerializer):
    complete_extra_form = serializers.CharField(read_only=True)
    sexy_role = serializers.CharField(read_only=True)
    mou = MOUSerializer()

    class Meta:
        model = MOUSignator
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'complete_extra_form',
            'mou',
            'sexy_role',
        ]

class MOUSignatureSerializer(serializers.ModelSerializer):
    from cis.serializers.highschool import HighSchoolSerializer
    from cis.serializers.highschool_admin import CustomUserSerializer

    signator_template = MOUSignatorSerializer()
    highschool = HighSchoolSerializer()
    signator = CustomUserSerializer()

    sexy_status = serializers.CharField(read_only=True)
    mou_pdf_url = serializers.CharField(read_only=True)
    is_signed = serializers.BooleanField(read_only=True)

    class Meta:
        model = MOUSignature
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'mou_pdf_url',
            'is_signed',
        ]
