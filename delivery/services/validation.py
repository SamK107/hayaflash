from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError

from delivery.models import Delivery

VALID_GEO_METHODS = {c.value for c in Delivery.GeoMethod}
MIN_ADDRESS_LENGTH = 10
MAX_DELIVERY_NOTES_LENGTH = 1000


def _parse_optional_decimal(value: Any, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field: "Invalid decimal value."}) from exc


def validate_coordinates(lat: Any, lng: Any) -> tuple[Decimal | None, Decimal | None]:
    """Strict range check for GPS coordinates."""
    lat_dec = _parse_optional_decimal(lat, "latitude")
    lng_dec = _parse_optional_decimal(lng, "longitude")

    if lat_dec is None and lng_dec is None:
        return None, None
    if lat_dec is None or lng_dec is None:
        raise ValidationError(
            {"delivery": "Both latitude and longitude are required when either is set."}
        )
    if not (-90 <= lat_dec <= 90):
        raise ValidationError({"latitude": "Latitude must be between -90 and 90."})
    if not (-180 <= lng_dec <= 180):
        raise ValidationError({"longitude": "Longitude must be between -180 and 180."})
    return lat_dec, lng_dec


def validate_delivery_input(data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize and validate delivery payload for order creation.
    Returns cleaned dict ready for Delivery model fields.

    Written address and voice note are interchangeable: many customers can't
    write, so at least one of the two must be present, but neither is
    individually mandatory once the other is. A short/empty address_text is
    only rejected when there is no voice note to fall back on.
    """
    if not isinstance(data, dict):
        raise ValidationError({"delivery": "Must be a JSON object."})

    raw_address = data.get("address_text")
    address_text = raw_address.strip() if isinstance(raw_address, str) else ""
    has_audio = bool(data.get("audio_base64"))

    if not address_text and not has_audio:
        raise ValidationError(
            {
                "delivery": (
                    "Provide a written address or record a voice note."
                )
            }
        )
    if address_text and not has_audio and len(address_text) < MIN_ADDRESS_LENGTH:
        raise ValidationError(
            {
                "address_text": (
                    f"Address must be at least {MIN_ADDRESS_LENGTH} characters "
                    "(or record a voice note instead)."
                )
            }
        )

    lat, lng = validate_coordinates(data.get("latitude"), data.get("longitude"))

    geo_method = data.get("geo_method") or Delivery.GeoMethod.MANUAL
    if geo_method not in VALID_GEO_METHODS:
        raise ValidationError({"geo_method": "Invalid geo_method value."})

    geo_accuracy = data.get("geo_accuracy")
    if geo_accuracy is not None and geo_accuracy != "":
        try:
            geo_accuracy_f = float(geo_accuracy)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"geo_accuracy": "Must be a number."}) from exc
        if geo_accuracy_f < 0:
            raise ValidationError({"geo_accuracy": "Must be >= 0."})
    else:
        geo_accuracy_f = None

    notes_raw = data.get("delivery_notes") or ""
    if not isinstance(notes_raw, str):
        raise ValidationError({"delivery_notes": "Must be a string."})
    delivery_notes = notes_raw.strip()
    if len(delivery_notes) > MAX_DELIVERY_NOTES_LENGTH:
        raise ValidationError(
            {
                "delivery_notes": (
                    f"Must be at most {MAX_DELIVERY_NOTES_LENGTH} characters."
                )
            }
        )

    return {
        "address_text": address_text,
        "latitude": lat,
        "longitude": lng,
        "geo_accuracy": geo_accuracy_f,
        "geo_method": geo_method,
        "delivery_notes": delivery_notes,
    }
