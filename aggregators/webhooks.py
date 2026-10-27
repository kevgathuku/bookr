"""Outbound partner webhooks: HMAC-signed POST with backoff retries."""

import hashlib
import hmac
import json
from urllib.request import Request, urlopen

from celery import shared_task

SIGNATURE_HEADER = "X-Webhook-Signature"


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, body), signature)


@shared_task(
    name="aggregators.send_webhook",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
def send_webhook(url, secret, event, payload):
    body = json.dumps({"event": event, "payload": payload}).encode()
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(secret, body),
        },
    )
    response = urlopen(request, timeout=10)
    try:
        return response.status
    finally:
        response.close()
