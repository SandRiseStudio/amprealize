# Notify

A multi-channel notification library supporting Email, Slack, SMS, and copy-link with a flexible template system.

## Features

- **Multi-Channel Support**: Email (SMTP/SendGrid), Slack, SMS (Twilio), and Copy-Link
- **Template System**: Jinja2-based templates for consistent messaging
- **Async-First**: Built for async operations with sync fallbacks
- **Provider Agnostic**: Swap providers without changing application code
- **Batch Operations**: Send notifications to multiple recipients efficiently
- **Delivery Tracking**: Track notification status and delivery receipts
- **Zero Core Dependencies**: Core functionality works without external services

## Installation

```bash
# Core only (templates + copy-link)
pip install notify

# With email support
pip install notify[email]

# With Slack support
pip install notify[slack]

# With SMS support
pip install notify[sms]

# All providers
pip install notify[all]
```

## Quick Start

```python
from notify import NotifyService, NotificationRequest, Channel

# Initialize service
service = NotifyService()

# Add providers
service.add_provider(EmailProvider(
    smtp_host="smtp.example.com",
    smtp_port=587,
    username="user",
    password="pass"
))

# Send notification
result = await service.send(NotificationRequest(
    channel=Channel.EMAIL,
    recipient="user@example.com",
    template="invite",
    context={
        "org_name": "Acme Corp",
        "invite_link": "https://app.example.com/invite/abc123",
        "inviter_name": "John Doe"
    }
))

print(result.status)  # NotificationStatus.DELIVERED
```

## Templates

Templates use Jinja2 and support multiple formats per notification type:

```
templates/
  invite/
    email.html
    email.txt
    slack.json
    sms.txt
  alert/
    email.html
    slack.json
```

### Using Custom Templates

```python
service = NotifyService(template_dir="/path/to/templates")
```

## Copy-Link Provider

For scenarios where you just need to generate a shareable link:

```python
from notify import CopyLinkProvider

provider = CopyLinkProvider(base_url="https://app.example.com")
result = await provider.send(NotificationRequest(
    channel=Channel.COPY_LINK,
    template="invite",
    context={"token": "abc123"}
))

print(result.link)  # https://app.example.com/invite/abc123
```

## Hooks

Integrate with your application's logging/metrics:

```python
def on_send(notification, result):
    logger.info(f"Sent {notification.template} via {notification.channel}")

def on_error(notification, error):
    logger.error(f"Failed: {error}")

service = NotifyService(
    on_send=on_send,
    on_error=on_error
)
```

## License

MIT
