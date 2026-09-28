"""Report card verification. Every report card issued once the term's results are fully published carries a
QR code to /verify/<token>, a public page that confirms the results, shows that they changed since, or says the
card is not valid. A report card printed before that is a draft: no QR and no record.

The token is random (144 bits) and says nothing about the student. The record keeps a snapshot of what the card
certifies (average, division, points, and each subject's term score and grade) and a hash of it: the same card
printed again with unchanged results keeps its token, changed results get a new one."""

import hashlib
import json
import re
import secrets
from base64 import b64encode
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

import frappe
from frappe.utils import flt, get_url, now_datetime

from smart_school.results import get_grade, get_subject_averages, is_term_summary_published, round_half_up

TOKEN_BYTES = 18  # 24 URL-safe characters
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
REVOKER_ROLES = ("Headmaster", "System Manager")
RATE_LIMIT = 30  # verification page requests per IP address...
RATE_WINDOW = 60  # ...in this many seconds


def new_token():
	return secrets.token_urlsafe(TOKEN_BYTES)


def one_decimal(value):
	return float(Decimal(str(flt(value))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def certified_results(result):
	"""What a report card certifies, from a Student Term Result: this is hashed. Each subject's term score has
	one decimal, so a mark changed without changing the grade still changes the hash."""
	averages = get_subject_averages(result.student, result.term)[0]
	return {
		"student": result.student,
		"term": result.term,
		"average": flt(result.average, 2),
		"division": result.division_display or result.division,
		"points": result.total_points,
		"subjects": [
			{
				"subject": subject,
				"score": one_decimal(averages[subject]),
				"grade": get_grade(round_half_up(averages[subject]))[0],
			}
			for subject in sorted(averages)
		],
	}


def results_hash(results):
	return hashlib.sha256(json.dumps(results, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def get_verification(result):
	"""The verification for this report card: the existing one while the results are unchanged, else a new
	record. None while the term's results are not fully published for the class (the card is a draft)."""
	if not is_term_summary_published(result.term, result.get("class")):
		return None
	results = certified_results(result)
	digest = results_hash(results)
	existing = frappe.db.get_value(
		"Report Card Verification",
		{"student": result.student, "term": result.term, "results_hash": digest, "revoked": 0},
		["name", "token"],
		as_dict=True,
	)
	if existing:
		return existing

	term = frappe.get_cached_value("Term", result.term, ["term_name", "academic_year"], as_dict=True)
	doc = frappe.get_doc(
		{
			"doctype": "Report Card Verification",
			"token": new_token(),
			"student": result.student,
			"class": result.get("class"),
			"term": result.term,
			"student_term_result": result.name,
			"issued_on": now_datetime(),
			"issued_by": frappe.session.user,
			"issued_via": issue_channel(),
			"results_hash": digest,
			"snapshot": json.dumps(
				{
					"student_name": frappe.db.get_value("Student", result.student, "full_name"),
					"class": result.get("class"),
					"term_name": term.term_name,
					"academic_year": term.academic_year,
					"results": results,
				},
				indent=1,
			),
		}
	).insert(ignore_permissions=True)
	# Report cards come from GET requests (print view, PDF downloads), which Frappe does not commit
	frappe.db.commit()
	return doc


def issue_channel():
	if frappe.flags.report_card_channel:
		return frappe.flags.report_card_channel
	request = getattr(frappe.local, "request", None)
	return "Class Print" if request and "download_multi_pdf" in (request.path or "") else "Desk Print"


def verify_url(token):
	"""Uses the site's host_name when it is set (e.g. the laptop's address for phones on the same network)."""
	return get_url(f"/verify/{token}")


def qr_data_uri(text):
	"""QR code as an SVG data URI, made offline with PyQRCode (already installed with Frappe)."""
	from pyqrcode import create

	stream = BytesIO()
	create(text, error="M").svg(stream, scale=3, module_color="#000", background="#fff", xmldecl=False)
	return "data:image/svg+xml;base64," + b64encode(stream.getvalue()).decode()


@frappe.whitelist()
def revoke(name, reason):
	"""Headmaster or System Manager: the token stops being valid (a reprint gets a new one)."""
	frappe.only_for(REVOKER_ROLES)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw("Give the reason for revoking this report card")
	doc = frappe.get_doc("Report Card Verification", name)
	if doc.revoked:
		frappe.throw("This report card is already revoked")
	doc.update(
		{"revoked": 1, "revoked_by": frappe.session.user, "revoked_on": now_datetime(), "revoke_reason": reason}
	)
	doc.save(ignore_permissions=True)


# ---------- the public page ----------


def within_rate_limit():
	key = frappe.cache.make_key(f"smart_school:verify:{frappe.local.request_ip or 'unknown'}")
	count = frappe.cache.incr(key)
	if count == 1:
		frappe.cache.expire(key, RATE_WINDOW)
	return count <= RATE_LIMIT


def get_verification_view(token):
	"""status "valid", "changed" or "invalid" (unknown or revoked token, told apart from nobody), with only what
	the report card showed: no contacts, fees, discipline, attendance or position."""
	record = None
	if token and TOKEN_PATTERN.match(token):
		record = frappe.db.get_value(
			"Report Card Verification",
			{"token": token, "revoked": 0},
			["issued_on", "results_hash", "snapshot", "student", "term"],
			as_dict=True,
		)
	if not record:
		return frappe._dict(status="invalid")

	issued = frappe._dict(json.loads(record.snapshot))
	view = frappe._dict(status="valid", issued=issued, issued_on=record.issued_on, current=None)
	result = frappe.db.get_value(
		"Student Term Result",
		{"student": record.student, "term": record.term},
		["name", "student", "term", "class", "average", "division", "division_display", "total_points"],
		as_dict=True,
	)
	current = certified_results(result) if result else None
	if current and results_hash(current) == record.results_hash:
		return view

	view.status = "changed"
	# Current results are shown only when they are published: an old QR must not reveal corrections in progress
	if result and is_term_summary_published(result.term, result["class"]):
		view.current = current
	else:
		view.current_hidden = True
	return view
