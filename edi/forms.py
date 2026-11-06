from django import forms

from .models import SubmissionBatch
from .remittance import MAX_835_BYTES


class RemittanceUploadForm(forms.Form):
    file = forms.FileField(label="Returned 835 file", help_text="ASCII X12 • maximum 2 MB")
    batch = forms.ModelChoiceField(
        queryset=SubmissionBatch.objects.all(), required=False,
        label="Submission batch (optional)",
        help_text="Select only when the sender confirms which submission this response belongs to.")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.size or upload.size > MAX_835_BYTES:
            raise forms.ValidationError("Choose a nonempty 835 file no larger than 2 MB.")
        return upload
