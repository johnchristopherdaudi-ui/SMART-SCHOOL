"""SMS providers: the part that talks to a gateway, one message at a time.

A provider is a class with `send(phone, text) -> SendResult`. It is registered in hooks.py under
`smart_school_sms_providers` ({name: dotted path}); Smart School Settings > SMS Provider picks one by name. A
provider with a different API (Beem, NextSMS, ...) is a new class and one hook line, in this app or another;
the queue, consent, limits and quiet hours in smart_school.sms stay as they are."""

from dataclasses import dataclass

import frappe

DEFAULT_PROVIDER = "Frappe SMS Settings"
TIMEOUT_SECONDS = 20


@dataclass
class SendResult:
	ok: bool
	message_id: str | None = None
	error: str | None = None
	retryable: bool = False  # network trouble or a server error: worth trying again later


class SMSProvider:
	name = None

	def is_configured(self):
		return True

	def send(self, phone, text):
		raise NotImplementedError


class FrappeSMSSettingsProvider(SMSProvider):
	"""The gateway set up in Frappe's SMS Settings (URL, parameters, headers). Frappe's own send_sms sends a list
	and hides which numbers failed, so each message is sent here on its own with the same settings."""

	name = DEFAULT_PROVIDER

	def is_configured(self):
		return bool(frappe.db.get_single_value("SMS Settings", "sms_gateway_url"))

	def send(self, phone, text):
		import requests

		from frappe.core.doctype.sms_settings.sms_settings import get_headers

		settings = frappe.get_doc("SMS Settings", "SMS Settings")
		if not settings.sms_gateway_url:
			return SendResult(False, error="SMS Settings has no gateway URL")
		headers = get_headers(settings)
		params = {settings.message_parameter: text, settings.receiver_parameter: phone}
		for p in settings.get("parameters"):
			if not p.header:
				params[p.parameter] = p.value

		kwargs = {"headers": headers, "timeout": TIMEOUT_SECONDS}
		if headers.get("Content-Type") == "application/json":
			kwargs["json"] = params
		elif settings.use_post:
			kwargs["data"] = params
		else:
			kwargs["params"] = params
		try:
			method = requests.post if settings.use_post else requests.get
			response = method(settings.sms_gateway_url, **kwargs)
		except requests.RequestException as e:
			return SendResult(False, error=f"Gateway not reached: {type(e).__name__}", retryable=True)
		if 200 <= response.status_code < 300:
			return SendResult(True, message_id=(response.text or "").strip()[:140] or None)
		return SendResult(
			False,
			error=f"Gateway answered {response.status_code}: {(response.text or '').strip()[:200]}",
			retryable=response.status_code >= 500 or response.status_code == 429,
		)


def get_provider_names():
	return list(frappe.get_hooks("smart_school_sms_providers") or {})


def get_provider(name=None):
	name = name or DEFAULT_PROVIDER
	paths = frappe.get_hooks("smart_school_sms_providers") or {}
	path = paths.get(name)
	if isinstance(path, list):  # a hook dict value can come back as a list of the apps' values
		path = path[-1]
	if not path:
		frappe.throw(f"No SMS provider called {name} is installed")
	return frappe.get_attr(path)()
