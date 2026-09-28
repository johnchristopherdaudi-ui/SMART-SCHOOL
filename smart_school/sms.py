"""SMS to parents: results, payment receipts, fee reminders and announcements, and nothing else.

Every message goes through the SMS Outbox. It is written for one guardian and checked there: consent
(Guardian.sms_opt_in, else Skipped), a Tanzanian mobile number (255XXXXXXXXX, else Failed with the reason) and an
editable Swahili template. A background job then sends what is due, outside the quiet hours (21:00-07:00: those
wait for the morning) and within the daily and monthly limits (in SMS, as the provider bills). Provider errors
are tried again a few times; messages still waiting after a few days are dropped (Skipped, Expired).

Smart School Settings > SMS Mode: Off creates nothing; Test does all of the above but records the message as
Test instead of sending it; Live sends through the provider (smart_school.sms_providers).

Early warnings, interventions, discipline and marks alerts are never sent by SMS: only the five message types
below exist, each tied to one kind of record."""

import math
import re
from datetime import datetime, timedelta

import frappe
from frappe.utils import (
	add_days,
	add_to_date,
	cint,
	flt,
	formatdate,
	get_datetime,
	get_first_day,
	get_time,
	get_url,
	getdate,
	now_datetime,
	today,
)

from smart_school.sms_providers import DEFAULT_PROVIDER, get_provider

OFF, TEST, LIVE = "Off", "Test", "Live"
QUEUED, SENT, FAILED, TESTED, SKIPPED = "Queued", "Sent", "Failed", "Test", "Skipped"

RESULTS = "Results Published"
RECEIPT = "Payment Received"
FEE_BEFORE_TERM = "Fee Reminder"
FEE_OVERDUE = "Fee Overdue"
ANNOUNCEMENT = "Announcement"
MESSAGE_TYPES = (RESULTS, RECEIPT, FEE_BEFORE_TERM, FEE_OVERDUE, ANNOUNCEMENT)
FEE_TYPES = (RECEIPT, FEE_BEFORE_TERM, FEE_OVERDUE)
REFERENCE_DOCTYPE = {
	RESULTS: "Exam",
	RECEIPT: "Fee Payment",
	FEE_BEFORE_TERM: "Term",
	FEE_OVERDUE: "Term",
	ANNOUNCEMENT: "Announcement",
}
# Records that stay inside the school: refused even if someone tries to queue them
FORBIDDEN_DOCTYPES = (
	"Student Intervention",
	"Risk Prediction",
	"Risk Model",
	"Discipline Record",
	"Marks Alert",
	"Performance Insight",
)

MANAGER_ROLES = ("Headmaster", "System Manager")  # bulk sends, templates, consent on paper, retries
FEE_ROLES = ("Accountant",)  # sees the fee messages only

DEFAULTS = {
	"sms_mode": OFF,
	"sms_provider": DEFAULT_PROVIDER,
	"sms_price": 25,
	"sms_daily_limit": 1500,
	"sms_monthly_limit": 5000,
	"sms_quiet_start": "21:00:00",
	"sms_quiet_end": "07:00:00",
	"sms_max_attempts": 3,
	"sms_expire_hours": 72,
	"sms_fee_days_before_term": 7,
	"sms_fee_overdue_days": 30,
}
RETRY_MINUTES = (5, 30, 120)  # after the 1st, 2nd and 3rd failed attempt
REMINDER_WINDOW_DAYS = 14  # an overdue reminder is due for 14 days, so switching it on does not dig up old terms
BATCH_SIZE = 500

# Short portal links keep a message in one SMS (hooks.website_redirects)
LINKS = {RESULTS: "/matokeo", RECEIPT: "/ada", FEE_BEFORE_TERM: "/ada", FEE_OVERDUE: "/ada", ANNOUNCEMENT: "/matangazo"}

PLACEHOLDERS = {
	RESULTS: ("shule", "mwanafunzi", "mtihani", "muhula", "wastani", "division", "kiungo"),
	RECEIPT: ("shule", "mwanafunzi", "kiasi", "muhula", "risiti", "salio"),
	FEE_BEFORE_TERM: ("shule", "mwanafunzi", "muhula", "tarehe", "kiasi", "deni", "kiungo"),
	FEE_OVERDUE: ("shule", "mwanafunzi", "muhula", "salio", "siku", "kiungo"),
	ANNOUNCEMENT: ("shule", "kichwa", "kiungo"),
}
PLACEHOLDER_HELP = {
	"shule": "school name for SMS (Settings)",
	"mwanafunzi": "student's name (shortened if the message would need 2 SMS)",
	"mtihani": "exam name",
	"muhula": "term",
	"wastani": "student's average in this exam, e.g. 58.3",
	"division": "', Division II' when the term result is complete, else nothing",
	"kiungo": "short link to the parent portal",
	"kiasi": "amount in TZS, e.g. 250,000",
	"risiti": "receipt number",
	"salio": "balance still owed, TZS",
	"tarehe": "date the term starts",
	"deni": "'; deni la nyuma TZS 150,000' when there is earlier debt, else nothing",
	"siku": "days since the term started",
	"kichwa": "announcement title (shortened to fit one SMS)",
}
DEFAULT_TEMPLATES = {
	RESULTS: "{shule}: {mwanafunzi} - {mtihani}: wastani {wastani}%{division}. Zaidi: {kiungo}",
	RECEIPT: "{shule}: Tumepokea TZS {kiasi} ada ya {mwanafunzi} ({muhula}). Risiti {risiti}. Salio TZS {salio}.",
	FEE_BEFORE_TERM: "{shule}: {muhula} inaanza {tarehe}. Ada ya {mwanafunzi}: TZS {kiasi}{deni}. Lipa: {kiungo}",
	FEE_OVERDUE: "{shule}: {mwanafunzi} ana deni la ada TZS {salio} ({muhula}, siku {siku}). Tafadhali lipa: {kiungo}",
	ANNOUNCEMENT: "{shule}: Tangazo - {kichwa}. Soma zaidi: {kiungo}",
}
# Long but real values: the template editor shows the message with these (after shortening, like a real one)
LONG_VALUES = {
	"mwanafunzi": "Anastazia Nyamizi Mwakalinga Mushi",
	"mtihani": "District Exam",
	"muhula": "Term 3 2026",
	"wastani": "100.0",
	"division": ", Division III",
	"kiasi": "1,500,000",
	"risiti": "RCPT-2026-00001",
	"salio": "1,500,000",
	"tarehe": "12-01-2027",
	"deni": "; deni la nyuma TZS 1,500,000",
	"siku": "120",
	"kichwa": "Mkutano wa wazazi na walimu wa Kidato cha Nne kuhusu maandalizi ya mtihani wa taifa",
}

PLACEHOLDER = re.compile(r"\{(\w+)\}")

# GSM 03.38: the basic set counts 1, the extension set 2 (escape + character); anything else makes it UCS-2
GSM7_BASIC = set(
	"@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
	"abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENDED = set("^{}\\[~]|€\f")


# ---------- settings ----------


def get_settings():
	s = frappe.get_cached_doc("Smart School Settings")
	value = lambda f: DEFAULTS[f] if s.get(f) in (None, "") else s.get(f)
	return frappe._dict(
		mode=value("sms_mode"),
		provider=value("sms_provider"),
		price=flt(value("sms_price")),
		daily_limit=cint(value("sms_daily_limit")),
		monthly_limit=cint(value("sms_monthly_limit")),
		quiet_start=get_time(value("sms_quiet_start")),
		quiet_end=get_time(value("sms_quiet_end")),
		max_attempts=cint(value("sms_max_attempts")),
		expire_hours=cint(value("sms_expire_hours")),
		fee_before_term=cint(s.get("sms_fee_reminder_before_term")),
		fee_days_before_term=cint(value("sms_fee_days_before_term")),
		fee_overdue=cint(s.get("sms_fee_reminder_overdue")),
		fee_overdue_days=cint(value("sms_fee_overdue_days")),
		school=get_school_name(s),
	)


def get_school_name(settings=None):
	settings = settings or frappe.get_cached_doc("Smart School Settings")
	from smart_school.branding import get_school_branding

	return (settings.get("sms_school_name") or "").strip() or get_school_branding().name


# ---------- length ----------


def measure(text):
	"""(characters, SMS, encoding). GSM-7: 160 in one SMS, 153 per part when longer; the extension characters
	^{}\\[~]|€ count 2. Any other character (an emoji, a curly quote) makes it UCS-2: 70, or 67 per part."""
	if all(c in GSM7_BASIC or c in GSM7_EXTENDED for c in text):
		units = sum(2 if c in GSM7_EXTENDED else 1 for c in text)
		single, part, encoding = 160, 153, "GSM-7"
	else:
		units = len(text.encode("utf-16-le")) // 2
		single, part, encoding = 70, 67, "UCS-2"
	segments = 1 if units <= single else math.ceil(units / part)
	return units, segments, encoding


# ---------- templates ----------


def get_template(message_type):
	"""The template's text, or None when it is switched off (then nothing of that type is written)."""
	row = frappe.db.get_value("SMS Template", message_type, ["message", "enabled"], as_dict=True)
	if not row:
		return DEFAULT_TEMPLATES[message_type]
	return row.message if row.enabled else None


def unknown_placeholders(message_type, template):
	return sorted(set(PLACEHOLDER.findall(template or "")) - set(PLACEHOLDERS[message_type]))


def render(template, values):
	"""Only {name} placeholders are filled (no Jinja, no str.format), so a template cannot run code."""
	return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "")), template)


def compose(message_type, values, template=None):
	"""The message, shortened to one SMS where the text allows: a student's name to first and last name, then
	first name and initial; an announcement's title cut with '...'."""
	template = template if template is not None else get_template(message_type)
	text = render(template, values)
	if measure(text)[1] == 1:
		return text
	if values.get("mwanafunzi"):
		for name in shorter_names(values["mwanafunzi"]):
			text = render(template, {**values, "mwanafunzi": name})
			if measure(text)[1] == 1:
				return text
	if values.get("kichwa"):
		title = values["kichwa"]
		room = 160 - measure(render(template, {**values, "kichwa": ""}))[0]
		if 3 < room < len(title):
			text = render(template, {**values, "kichwa": title[: room - 3].rstrip() + "..."})
	return text


def shorter_names(full_name):
	parts = (full_name or "").split()
	if len(parts) > 2:
		yield f"{parts[0]} {parts[-1]}"
	if len(parts) > 1:
		yield f"{parts[0]} {parts[-1][0]}."


def link(message_type):
	return get_url(LINKS[message_type])


def money(value):
	return f"{flt(value):,.0f}"


def long_values(message_type):
	values = {k: v for k, v in LONG_VALUES.items() if k in PLACEHOLDERS[message_type]}
	values.update(shule=get_school_name(), kiungo=link(message_type))
	exam_names = frappe.get_all("Exam", pluck="exam_name", distinct=True) + frappe.get_all(
		"External Exam Type", pluck="name"
	)
	longest = max(exam_names or [LONG_VALUES["mtihani"]], key=len)
	values["mtihani"] = max(longest, LONG_VALUES["mtihani"], key=len)
	return values


@frappe.whitelist()
def preview_template(message_type, message):
	"""For the template editor: the length of the text as typed, and a message made with long real values."""
	frappe.only_for(MANAGER_ROLES)
	if message_type not in MESSAGE_TYPES:
		frappe.throw("Unknown SMS type")
	units, segments, encoding = measure(message or "")
	example = compose(message_type, long_values(message_type), template=message or "")
	e_units, e_segments, e_encoding = measure(example)
	return {
		"characters": units,
		"segments": segments,
		"encoding": encoding,
		"example": example,
		"example_characters": e_units,
		"example_segments": e_segments,
		"example_encoding": e_encoding,
		"unknown": unknown_placeholders(message_type, message),
		"placeholders": {p: PLACEHOLDER_HELP[p] for p in PLACEHOLDERS[message_type]},
	}


# ---------- numbers and quiet hours ----------


def normalize_phone(phone):
	from smart_school.portal_utils import normalize_tz_mobile

	return normalize_tz_mobile(phone)


def in_quiet_hours(moment, settings):
	t = get_datetime(moment).time()
	start, end = settings.quiet_start, settings.quiet_end
	if start == end:
		return False
	if start > end:  # over midnight, e.g. 21:00-07:00
		return t >= start or t < end
	return start <= t < end


def next_send_time(moment, settings):
	"""moment itself, or the end of the quiet hours it falls in."""
	moment = get_datetime(moment)
	if not in_quiet_hours(moment, settings):
		return moment
	end = datetime.combine(moment.date(), settings.quiet_end)
	return end if end > moment else end + timedelta(days=1)


# ---------- writing messages ----------


def assert_allowed(message_type, reference_doctype):
	if reference_doctype in FORBIDDEN_DOCTYPES:
		frappe.throw(f"{reference_doctype} is never sent by SMS")
	if message_type not in MESSAGE_TYPES:
		frappe.throw(f"{message_type} is not an SMS type")
	if REFERENCE_DOCTYPE[message_type] != reference_doctype:
		frappe.throw(f"A {message_type} SMS must refer to a {REFERENCE_DOCTYPE[message_type]}")


def dedupe_key(message_type, reference_name, guardian, student=None):
	return "|".join([message_type, reference_name, guardian, student or ""])


def build(message_type, reference_name, guardian, values, student=None, settings=None, template=None):
	"""The SMS Outbox row for one guardian, not saved: its status says whether it will be sent."""
	settings = settings or get_settings()
	text = compose(message_type, {"shule": settings.school, "kiungo": link(message_type), **values}, template)
	units, segments, encoding = measure(text)
	doc = frappe.new_doc("SMS Outbox")
	doc.update(
		{
			"message_type": message_type,
			"mode": settings.mode,
			"guardian": guardian.name,
			"guardian_name": guardian.full_name,
			"student": student,
			"phone_entered": guardian.phone,
			"message": text,
			"characters": units,
			"segments": segments,
			"encoding": encoding,
			"estimated_cost": segments * settings.price,
			"reference_doctype": REFERENCE_DOCTYPE[message_type],
			"reference_name": reference_name,
			"dedupe_key": dedupe_key(message_type, reference_name, guardian.name, student),
		}
	)
	check_recipient(doc, guardian)
	if doc.status == QUEUED:
		doc.send_after = next_send_time(now_datetime(), settings)
	return doc


def check_recipient(doc, guardian):
	"""Consent first (Skipped), then the number (Failed with the reason); otherwise Queued."""
	doc.error = None
	if not cint(guardian.sms_opt_in):
		doc.status, doc.error = SKIPPED, "The guardian has not agreed to receive SMS"
	elif not (guardian.phone or "").strip():
		doc.status, doc.error = FAILED, "No phone number"
	else:
		doc.phone = normalize_phone(guardian.phone)
		if doc.phone:
			doc.status = QUEUED
		else:
			doc.status, doc.error = FAILED, f"Not a Tanzanian mobile number: {guardian.phone}"


def queue_messages(message_type, reference_name, recipients, batch=None):
	"""recipients: [(guardian, values, student)]. Writes one SMS Outbox row per new recipient and starts the
	sending job. Returns the names written (none when SMS are off, the template is off, or all were written
	before)."""
	assert_allowed(message_type, REFERENCE_DOCTYPE.get(message_type))
	settings = get_settings()
	template = get_template(message_type)
	if settings.mode == OFF or template is None:
		return []
	names, queued = [], False
	for guardian, values, student in recipients:
		doc = build(message_type, reference_name, guardian, values, student, settings, template)
		if frappe.db.exists("SMS Outbox", {"dedupe_key": doc.dedupe_key}):
			continue  # once per exam, payment, reminder or announcement, even after publishing again
		doc.batch = batch
		doc.insert(ignore_permissions=True)
		names.append(doc.name)
		queued = queued or doc.status == QUEUED
	if queued:
		start_sending()
	return names


def start_sending():
	frappe.enqueue(
		"smart_school.sms.process_queue",
		queue="short",
		job_id=f"smart_school_sms_queue::{frappe.local.site}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def preview(message_type, reference_name, recipients):
	"""What a bulk send would do, for the confirmation dialog: nothing is written."""
	settings = get_settings()
	template = get_template(message_type)
	result = frappe._dict(
		mode=settings.mode,
		template_enabled=template is not None,
		messages=0,
		sms=0,
		cost=0.0,
		skipped=0,
		failed=0,
		already=0,
		price=settings.price,
	)
	if settings.mode == OFF or template is None:
		return result
	for guardian, values, student in recipients:
		doc = build(message_type, reference_name, guardian, values, student, settings, template)
		if frappe.db.exists("SMS Outbox", {"dedupe_key": doc.dedupe_key}):
			result.already += 1
		elif doc.status == SKIPPED:
			result.skipped += 1
		elif doc.status == FAILED:
			result.failed += 1
		else:
			result.messages += 1
			result.sms += doc.segments
	result.cost = result.sms * settings.price
	result.update(remaining(settings))
	result.fits_month = result.sms <= result.remaining_month
	result.days = math.ceil(result.sms / settings.daily_limit) if settings.daily_limit and result.sms else 0
	return result


# ---------- sending ----------


def usage(moment=None):
	"""SMS (segments) used today and this month: sent, or recorded in Test mode."""
	moment = get_datetime(moment or now_datetime())
	day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
	month = day.replace(day=1)
	used = lambda since: cint(
		frappe.db.sql(
			"""select coalesce(sum(segments), 0) from `tabSMS Outbox`
			where status in (%(sent)s, %(tested)s) and sent_on >= %(since)s""",
			{"sent": SENT, "tested": TESTED, "since": since},
		)[0][0]
	)
	return used(day), used(month)


def remaining(settings, moment=None):
	"""What is left today and this month, counting what already waits in the queue."""
	today_used, month_used = usage(moment)
	waiting = cint(
		frappe.db.sql("select coalesce(sum(segments), 0) from `tabSMS Outbox` where status = %s", QUEUED)[0][0]
	)
	return {
		"used_today": today_used,
		"used_month": month_used,
		"waiting": waiting,
		"daily_limit": settings.daily_limit,
		"monthly_limit": settings.monthly_limit,
		"remaining_today": max(settings.daily_limit - today_used - waiting, 0),
		"remaining_month": max(settings.monthly_limit - month_used - waiting, 0),
	}


def process_queue(moment=None):
	"""Send (Live) or record (Test) the queued messages that are due. Runs from the scheduler every 5 minutes
	and right after messages are written; one run at a time."""
	lock = frappe.cache.lock(f"{frappe.local.site}:smart_school_sms_queue", timeout=900)
	if not lock.acquire(blocking=False):
		return
	try:
		send_due(moment)
	finally:
		try:
			lock.release()
		except Exception:
			pass  # expired: another run may already hold it


def send_due(moment=None):
	settings = get_settings()
	moment = get_datetime(moment or now_datetime())
	if settings.mode == OFF:
		for name in frappe.get_all("SMS Outbox", filters={"status": QUEUED}, pluck="name"):
			set_status(name, SKIPPED, error="SMS were turned off before this message was sent")
		commit()
		return
	if in_quiet_hours(moment, settings):
		return
	provider = get_provider(settings.provider) if settings.mode == LIVE else None
	used_today, used_month = usage(moment)
	due = frappe.get_all(
		"SMS Outbox",
		filters={"status": QUEUED, "send_after": ["<=", moment]},
		fields=["name", "guardian", "phone", "message", "segments", "attempts", "creation"],
		order_by="send_after asc, creation asc",
		limit=BATCH_SIZE,
	)
	for i, row in enumerate(due):
		if settings.expire_hours and get_datetime(row.creation) < moment - timedelta(hours=settings.expire_hours):
			set_status(row.name, SKIPPED, error=f"Expired: not sent within {settings.expire_hours} hours")
			continue
		if not cint(frappe.db.get_value("Guardian", row.guardian, "sms_opt_in")):
			set_status(row.name, SKIPPED, error="The guardian withdrew consent before it was sent")
			continue
		if settings.monthly_limit and used_month + row.segments > settings.monthly_limit:
			first_of_next = get_first_day(add_to_date(moment, months=1))
			postpone(due[i:], datetime.combine(first_of_next, settings.quiet_end), "Monthly SMS limit reached")
			break
		if settings.daily_limit and used_today + row.segments > settings.daily_limit:
			tomorrow = add_days(moment.date(), 1)
			postpone(due[i:], datetime.combine(tomorrow, settings.quiet_end), "Daily SMS limit reached")
			break
		if send_one(row, settings, provider, moment):
			used_today += row.segments
			used_month += row.segments
		commit()
	commit()


def send_one(row, settings, provider, moment):
	"""True when the message counts against the limits (sent, or recorded in Test mode)."""
	if settings.mode == TEST:
		set_status(row.name, TESTED, sent_on=moment, provider="Test mode (not sent)")
		return True
	attempts = cint(row.attempts) + 1
	result = provider.send(row.phone, row.message)
	if result.ok:
		set_status(
			row.name, SENT, sent_on=moment, attempts=attempts, provider=provider.name, provider_message_id=result.message_id
		)
		return True
	if result.retryable and attempts < settings.max_attempts:
		wait = RETRY_MINUTES[min(attempts, len(RETRY_MINUTES)) - 1]
		set_status(
			row.name, QUEUED, attempts=attempts, error=result.error, send_after=moment + timedelta(minutes=wait)
		)
	else:
		set_status(row.name, FAILED, attempts=attempts, error=result.error, provider=provider.name)
	return False


def postpone(rows, when, reason):
	for row in rows:
		frappe.db.set_value("SMS Outbox", row.name, {"send_after": when, "error": reason}, update_modified=False)


def set_status(name, status, **values):
	frappe.db.set_value("SMS Outbox", name, {"status": status, **values})


def commit():
	frappe.db.commit()  # each message's status is kept even if the job stops half way


@frappe.whitelist()
def retry(names):
	"""Failed (or Skipped) messages are checked again against the guardian's current number and consent."""
	frappe.only_for(MANAGER_ROLES)
	names = frappe.parse_json(names) if isinstance(names, str) else names
	settings = get_settings()
	if settings.mode == OFF:
		frappe.throw("SMS are turned off (Smart School Settings > SMS Mode)")
	queued = 0
	for name in names:
		doc = frappe.get_doc("SMS Outbox", name)
		if doc.status not in (FAILED, SKIPPED):
			continue
		guardian = frappe.get_doc("Guardian", doc.guardian)
		doc.phone_entered = guardian.phone
		check_recipient(doc, guardian)
		doc.attempts = 0
		doc.mode = settings.mode
		doc.send_after = next_send_time(now_datetime(), settings) if doc.status == QUEUED else None
		doc.save(ignore_permissions=True)
		queued += doc.status == QUEUED
	if queued:
		start_sending()
	return queued


# ---------- recipients ----------


def guardians_by_student(students):
	"""{student: [guardian]}: every guardian linked to the student (consent is checked per message)."""
	links = frappe.get_all(
		"Guardian Student Link",
		filters={"student": ["in", list(students) or [""]], "parenttype": "Guardian"},
		fields=["parent", "student"],
		order_by="parent asc",
	)
	guardians = {
		g.name: g
		for g in frappe.get_all(
			"Guardian",
			filters={"name": ["in", list({l.parent for l in links}) or [""]]},
			fields=["name", "full_name", "phone", "sms_opt_in"],
		)
	}
	result = {}
	for l in links:
		if l.parent in guardians:
			result.setdefault(l.student, []).append(guardians[l.parent])
	return result


def student_names(students):
	return dict(frappe.get_all("Student", filters={"name": ["in", list(students) or [""]]}, fields=["name", "full_name"], as_list=True))


# ---------- results ----------


def exam_result_recipients(exam):
	"""One message per student (to each of their guardians): the student's average in this exam and, when every
	other exam of the term is published too, the term's division."""
	from smart_school.results import INCOMPLETE

	exam = frappe.get_doc("Exam", exam) if isinstance(exam, str) else exam
	averages = {}
	for r in frappe.get_all(
		"Exam Result", filters={"exam": exam.name, "docstatus": 1}, fields=["student", "percentage"]
	):
		averages.setdefault(r.student, []).append(flt(r.percentage))
	others = frappe.get_all(
		"Exam",
		filters={"term": exam.term, "class": exam.get("class"), "name": ["!=", exam.name]},
		pluck="results_published",
	)
	term_complete = all(others)  # this exam is being published
	divisions = {}
	if term_complete and averages:
		divisions = dict(
			frappe.get_all(
				"Student Term Result",
				filters={"term": exam.term, "student": ["in", list(averages)]},
				fields=["student", "division"],
				as_list=True,
			)
		)
	names = student_names(averages)
	guardians = guardians_by_student(averages)
	recipients = []
	for student in sorted(averages):
		marks = averages[student]
		division = divisions.get(student)
		values = {
			"mwanafunzi": names.get(student, student),
			"mtihani": exam.exam_name,
			"muhula": exam.term,
			"wastani": f"{half_up(sum(marks) / len(marks), 1):.1f}",
			"division": f", {division}" if division and division != INCOMPLETE else "",
		}
		for guardian in guardians.get(student, []):
			recipients.append((guardian, values, student))
	return recipients


def half_up(value, digits=0):
	from decimal import ROUND_HALF_UP, Decimal

	return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


@frappe.whitelist()
def preview_exam_results(exam):
	frappe.only_for(MANAGER_ROLES)
	return preview(RESULTS, exam, exam_result_recipients(exam))


def queue_exam_results(exam, batch=None):
	return queue_messages(RESULTS, exam, exam_result_recipients(exam), batch=batch or f"Results {exam}")


# ---------- payments ----------


def queue_payment_receipt(payment):
	"""One receipt per payment to each guardian of the student; never blocks the payment itself."""
	try:
		payment = frappe.get_doc("Fee Payment", payment) if isinstance(payment, str) else payment
		values = {
			"mwanafunzi": frappe.db.get_value("Student", payment.student, "full_name"),
			"kiasi": money(payment.amount_paid),
			"muhula": payment.term,
			"risiti": payment.receipt_number or payment.name,
			"salio": money(payment.balance),
		}
		guardians = guardians_by_student([payment.student]).get(payment.student, [])
		return queue_messages(RECEIPT, payment.name, [(g, values, payment.student) for g in guardians])
	except Exception:
		frappe.log_error(title=f"SMS receipt for {getattr(payment, 'name', payment)} not written")
		return []


# ---------- fee reminders ----------


def fee_reminder_recipients(kind, on_date=None):
	"""{term: [(guardian, values, student)]} of the reminders due on on_date.

	Before term: from X days before a term starts until it starts, for active students still at school when it
	starts, if they owe something for it or from before. Overdue: once a term is Y days old, for 14 days, for
	every student who still owes for that term; a student who left owes nothing for terms after leaving
	(get_fee_statement), so no reminder is sent for those."""
	from smart_school.fees import get_fee_statement

	settings = get_settings()
	on_date = getdate(on_date or today())
	terms = frappe.get_all("Term", fields=["name", "start_date"], filters={"start_date": ["is", "set"]})
	if kind == FEE_BEFORE_TERM:
		days = settings.fee_days_before_term
		due_terms = [t for t in terms if on_date < getdate(t.start_date) <= add_days(on_date, days)]
	else:
		days = settings.fee_overdue_days
		due_terms = [
			t
			for t in terms
			if add_days(t.start_date, days) <= on_date < add_days(t.start_date, days + REMINDER_WINDOW_DAYS)
		]

	result = {}
	for term in sorted(due_terms, key=lambda t: t.start_date):
		start = getdate(term.start_date)
		# Before a term: students who will be in it. Overdue: anyone still at school when it started
		filters = {"status": "Active"} if kind == FEE_BEFORE_TERM else {}
		students = [
			s
			for s in frappe.get_all("Student", filters=filters, fields=["name", "full_name", "exit_date"])
			if not s.exit_date or getdate(s.exit_date) > start
		]
		guardians = guardians_by_student([s.name for s in students])
		recipients = []
		for student in students:
			if not guardians.get(student.name):
				continue
			statement = get_fee_statement(student.name)
			row = next((r for r in statement.rows if r.term == term.name), None)
			if kind == FEE_BEFORE_TERM:
				owed_now = flt(row.remaining) if row else 0
				earlier = flt(statement.balance)
				if owed_now <= 0 and earlier <= 0:
					continue
				values = {
					"mwanafunzi": student.full_name,
					"muhula": term.name,
					"tarehe": formatdate(start, "dd-mm-yyyy"),
					"kiasi": money(owed_now),
					"deni": f"; deni la nyuma TZS {money(earlier)}" if earlier > 0 else "",
				}
			else:
				if not row or not row.is_due or flt(row.remaining) <= 0:
					continue
				values = {
					"mwanafunzi": student.full_name,
					"muhula": term.name,
					"salio": money(row.remaining),
					"siku": str((on_date - start).days),
				}
			for guardian in guardians[student.name]:
				recipients.append((guardian, values, student.name))
		result[term.name] = recipients
	return result


def send_fee_reminders():
	"""Daily: the reminders whose switch is on in Smart School Settings."""
	settings = get_settings()
	if settings.mode == OFF:
		return
	for kind, switched_on in ((FEE_BEFORE_TERM, settings.fee_before_term), (FEE_OVERDUE, settings.fee_overdue)):
		if not switched_on:
			continue
		for term, recipients in fee_reminder_recipients(kind).items():
			queue_messages(kind, term, recipients, batch=f"{kind} {term} {today()}")


@frappe.whitelist()
def preview_fee_reminders(kind):
	"""For the switch in Smart School Settings: who would get a reminder today, and what it would cost; and when
	the next term's reminders start if none are due today."""
	frappe.only_for(MANAGER_ROLES)
	if kind not in (FEE_BEFORE_TERM, FEE_OVERDUE):
		frappe.throw("Unknown reminder")
	by_term = fee_reminder_recipients(kind)
	recipients = [r for rows in by_term.values() for r in rows]
	# each term separately (a reminder is once per term), then added up
	parts = [preview(kind, term, rows) for term, rows in by_term.items() if rows] or [preview(kind, "", [])]
	result = parts[0]
	for p in parts[1:]:
		for key in ("messages", "sms", "cost", "skipped", "failed", "already"):
			result[key] += p[key]
	if "remaining_month" in result:
		result.fits_month = result.sms <= result.remaining_month
	result.guardians = len({g.name for g, _, _ in recipients})
	result.students = len({s for _, _, s in recipients})
	result.terms = list(by_term)
	if kind == FEE_BEFORE_TERM and not recipients:
		upcoming = frappe.get_all(
			"Term", filters={"start_date": [">", today()]}, fields=["name", "start_date"], order_by="start_date asc", limit=1
		)
		if upcoming:
			days = get_settings().fee_days_before_term
			result.next_term = upcoming[0].name
			result.next_date = add_days(upcoming[0].start_date, -days)
	return result


# ---------- announcements ----------


def announcement_recipients(announcement):
	"""One message per guardian of the active students the announcement is for."""
	doc = frappe.get_doc("Announcement", announcement) if isinstance(announcement, str) else announcement
	filters = {"status": "Active"}
	if doc.audience != "All School":
		filters["current_class"] = ["in", [c.get("class") for c in doc.get("classes") or []] or [""]]
	students = frappe.get_all("Student", filters=filters, pluck="name")
	seen, recipients = set(), []
	for student, guardians in sorted(guardians_by_student(students).items()):
		for guardian in guardians:
			if guardian.name not in seen:
				seen.add(guardian.name)
				recipients.append((guardian, {"kichwa": doc.title}, None))
	return recipients


@frappe.whitelist()
def preview_announcement(announcement):
	frappe.only_for(MANAGER_ROLES)
	return preview(ANNOUNCEMENT, announcement, announcement_recipients(announcement))


@frappe.whitelist()
def send_announcement(announcement):
	frappe.only_for(MANAGER_ROLES)
	doc = frappe.get_doc("Announcement", announcement)
	if doc.get("sms_sent_on"):
		frappe.throw("This announcement was already sent by SMS")
	recipients = announcement_recipients(doc)
	check = preview(ANNOUNCEMENT, doc.name, recipients)
	if check.mode == OFF:
		frappe.throw("SMS are turned off (Smart School Settings > SMS Mode)")
	if not check.fits_month:
		frappe.throw(f"This needs {check.sms} SMS but only {check.remaining_month} are left this month")
	names = queue_messages(ANNOUNCEMENT, doc.name, recipients, batch=f"Announcement {doc.name}")
	doc.db_set({"sms_sent_on": now_datetime(), "sms_messages": len(names)})
	return len(names)


# ---------- consent ----------


def set_consent(guardian, opt_in, source, on_date=None):
	doc = frappe.get_doc("Guardian", guardian) if isinstance(guardian, str) else guardian
	doc.sms_opt_in = cint(opt_in)
	doc.flags.sms_consent = frappe._dict(source=source, date=getdate(on_date or today()))
	doc.save(ignore_permissions=True)
	return doc


@frappe.whitelist()
def set_consent_for_guardians(guardians, opt_in=1, consent_date=None):
	"""Consent collected on paper, for many guardians at once (source Staff, with the date on the paper)."""
	frappe.only_for(MANAGER_ROLES)
	guardians = frappe.parse_json(guardians) if isinstance(guardians, str) else guardians
	consent_date = getdate(consent_date or today())
	if consent_date > getdate(today()):
		frappe.throw("The consent date cannot be in the future")
	for name in guardians:
		set_consent(name, opt_in, "Staff", consent_date)
	return len(guardians)


@frappe.whitelist()
def set_my_consent(enabled):
	"""The parent portal switch: a guardian changes their own consent only."""
	from smart_school.portal_utils import get_logged_in_guardian

	guardian = get_logged_in_guardian()
	set_consent(guardian, cint(enabled), "Portal")
	return {"sms_opt_in": cint(enabled)}


# ---------- permissions ----------


def get_permission_query(user=None):
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if user == "Administrator" or set(MANAGER_ROLES) & set(roles):
		return None
	if set(FEE_ROLES) & set(roles):
		return "`tabSMS Outbox`.message_type in ({})".format(", ".join(frappe.db.escape(t) for t in FEE_TYPES))
	return "1=0"


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if user == "Administrator" or set(MANAGER_ROLES) & set(roles):
		return True
	if set(FEE_ROLES) & set(roles):
		return doc.get("message_type") in FEE_TYPES
	return False
