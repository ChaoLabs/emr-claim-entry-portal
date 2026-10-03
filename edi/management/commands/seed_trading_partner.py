from django.core.management.base import BaseCommand

from edi.models import TradingPartner

NAME = "Demo MAC Test"


class Command(BaseCommand):
    help = "Create or refresh a fictional trading partner for local testing."

    def handle(self, *args, **options):
        partner, created = TradingPartner.objects.update_or_create(
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
        self.stdout.write(("created " if created else "refreshed ") + partner.name)
