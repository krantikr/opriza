"""Notifications: channel port, adapters, and the raising service."""

from app.services.notifications.channels import Channel, DeliveryResult, get_channel
from app.services.notifications.service import NotificationService, NotifyResult

__all__ = ["Channel", "DeliveryResult", "get_channel", "NotificationService", "NotifyResult"]
