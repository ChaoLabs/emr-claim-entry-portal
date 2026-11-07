from django.core.management.base import BaseCommand

from edi.models import TradingPartner

NAME = "Demo MAC Test"


def ensure_demo_partner():
    """Create a test receiver once; preserve every operator-edited setting."""
    return TradingPartner.objects.get_or_create(
        name=NAME,
        defaults={
            "is_active": True,
            "isa_sender_qualifier": "ZZ",
            "isa_sender_id": "EMRTSDEMO",
            "isa_receiver_qualifier": "ZZ",
            "isa_receiver_id": "DEMOMAC",
            "usage_indicator": TradingPartner.USAGE_TEST,
            "gs_sender_code": "EMRTSDEMO",
            "gs_receiver_code": "DEMOMAC",
            "submitter_name": "EMRTS Demo Clinic",
            "submitter_id": "EMRTSDEMO",
            "submitter_contact_name": "Demo Support",
            "submitter_contact_phone": "9195550100",
            "receiver_name": "Demo MAC",
            "receiver_id": "DEMOMAC",
        },
    )


class Command(BaseCommand):
    help = "Create a fictional test trading partner without replacing existing settings."

    def handle(self, *args, **options):
        partner, created = ensure_demo_partner()
        self.stdout.write(("created " if created else "preserved existing ") + partner.name)
