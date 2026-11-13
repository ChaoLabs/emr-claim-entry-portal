"""Browser workflow helpers shared by claim capture regression tests."""
from django.urls import reverse


def submit_new_claim(client, data):
    """Open a fresh form and submit using the draft credentials it issued."""
    url = reverse("claims:capture_claim")
    form = client.get(url).context
    return client.post(url, {
        **data, "draft_token": form["draft_token"],
        "draft_version": form["draft_version"], "action": "submit",
    })
