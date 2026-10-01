"""Leave requests (ruhusa): a parent asks on the portal, the class teacher or the Headmaster decides.

- The parent asks for one of their own active children: dates (at most "Leave Requests: Days Back" days back, 7 by
  default), a short reason in Swahili, and optionally a doctor's note or other file (PDF or picture, 5 MB at most,
  kept private). The class teacher gets a ToDo; without one, the Headmaster(s).
- The class teacher of the student's class, or the Headmaster / System Manager, approves or rejects, with a short
  note for the parent. The parent sees the status on the portal, and gets an SMS if they agreed to SMS.
- Approved: the school days of the period already recorded Absent become Excused; Present and Late stay as they are
  (the child came). Days recorded later are shown Excused in Class Attendance. Withdrawn by the Headmaster
  afterwards: only the records the leave changed (and still Excused) go back to Absent.
- The reason and the file are seen by the Headmaster and the class teacher only (and the parent who wrote them);
  attendance shows "Excused", nothing more."""

import base64
import re

import frappe
from frappe.utils import add_days, cint, getdate, now_datetime, today

from smart_school.interventions import class_teacher_classes
from smart_school.school_calendar import SchoolCalendar

PENDING, APPROVED, REJECTED, CANCELLED = "Pending", "Approved", "Rejected", "Cancelled"
DECIDER_ROLES = ("Headmaster", "System Manager")
MAX_REASON = 500
MAX_FILE_BYTES = 5 * 1024 * 1024
FILE_TYPES = {"pdf": b"%PDF", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff", "png": b"\x89PNG"}
DEFAULT_DAYS_BACK = 7


def has_full_access(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(DECIDER_ROLES) & set(frappe.get_roles(user)))


def days_back():
	# get_single_value reads a value never stored as 0; 0 set on purpose means "from today"
	stored = frappe.db.sql(
		"select value from `tabSingles` where doctype = 'Smart School Settings' and field = 'leave_days_back'"
	)
	return cint(stored[0][0]) if stored and stored[0][0] not in (None, "") else DEFAULT_DAYS_BACK


# ---------- permissions (desk) ----------


def get_permission_query(user=None):
	user = user or frappe.session.user
	if has_full_access(user):
		return None
	classes = class_teacher_classes(user) if "Teacher" in frappe.get_roles(user) else []
	if not classes:
		return "1=0"
	return "`tabLeave Request`.`class` in ({})".format(", ".join(frappe.db.escape(c) for c in classes))


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if has_full_access(user):
		return True
	if "Teacher" not in frappe.get_roles(user) or ptype in ("create", "delete"):
		return False
	return doc.get("class") in class_teacher_classes(user)


# ---------- the parent's side (portal, Swahili) ----------


def portal_guardian():
	from smart_school.portal_utils import get_logged_in_guardian

	return get_logged_in_guardian()


def guardian_children(guardian):
	return [row.student for row in guardian.students]


@frappe.whitelist()
def submit_request(student, from_date, to_date, reason, file_name=None, file_data=None):
	"""A parent's request for their own child. file_data: the file as base64 (from the portal form)."""
	guardian = portal_guardian()
	if student not in guardian_children(guardian):
		frappe.throw("Mwanafunzi huyu hajaunganishwa na akaunti yako.", frappe.PermissionError)
	status, class_name = frappe.db.get_value("Student", student, ["status", "current_class"])
	if status != "Active":
		frappe.throw("Ruhusa inaombwa kwa mwanafunzi anayesoma shuleni sasa tu.")
	start, end = getdate(from_date), getdate(to_date)
	reason = (reason or "").strip()
	problems = []
	if end < start:
		problems.append("Tarehe ya mwisho iko kabla ya tarehe ya kuanza.")
	if start < getdate(add_days(today(), -days_back())):
		problems.append(f"Ruhusa inaweza kuombwa hadi siku {days_back()} nyuma tu.")
	if not reason:
		problems.append("Andika sababu fupi ya ruhusa.")
	elif len(reason) > MAX_REASON:
		problems.append(f"Sababu ni ndefu mno: herufi {MAX_REASON} ndizo nyingi zaidi.")
	content = check_file(file_name, file_data, problems) if file_data else None
	if not problems and overlapping(student, start, end):
		problems.append("Tayari kuna ombi la ruhusa (linalosubiri au lililoidhinishwa) kwa siku hizo.")
	if problems:
		frappe.throw("<br>".join(problems), title="Tafadhali rekebisha")

	doc = frappe.get_doc(
		{
			"doctype": "Leave Request",
			"student": student,
			"class": class_name,
			"guardian": guardian.name,
			"from_date": start,
			"to_date": end,
			"reason": reason,
			"status": PENDING,
		}
	)
	doc.flags.from_portal = True
	doc.insert(ignore_permissions=True)
	if content:
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": safe_file_name(file_name),
				"content": content,
				"is_private": 1,
				"attached_to_doctype": "Leave Request",
				"attached_to_name": doc.name,
				"attached_to_field": "attachment",
			}
		).insert(ignore_permissions=True)
		doc.db_set("attachment", file.file_url)
	notify_deciders(doc)
	return doc.name


def check_file(file_name, file_data, problems):
	"""A PDF or a picture of 5 MB at most, checked by its first bytes too (not only by its name)."""
	extension = (file_name or "").rsplit(".", 1)[-1].lower() if "." in (file_name or "") else ""
	try:
		content = base64.b64decode(str(file_data).split(",", 1)[-1], validate=True)
	except Exception:
		problems.append("Faili halikusomeka. Jaribu tena.")
		return None
	if extension not in FILE_TYPES or not content.startswith(FILE_TYPES[extension]):
		problems.append("Kiambatisho kiwe PDF au picha (JPG au PNG).")
	elif len(content) > MAX_FILE_BYTES:
		problems.append("Kiambatisho kisizidi MB 5.")
	elif extension == "pdf" and not safe_pdf(content):
		problems.append("PDF hii haisomeki au ina maudhui yasiyo salama. Tuma PDF nyingine au picha.")
	return content


def safe_pdf(content):
	"""Frappe refuses a PDF with JavaScript when it is saved; checked here first so the parent reads why in Swahili."""
	from frappe.utils.pdf import pdf_contains_js

	try:
		return not pdf_contains_js(content)
	except Exception:
		return False


def safe_file_name(name):
	base = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "kiambatisho")[-80:]
	return base or "kiambatisho"


def overlapping(student, start, end, exclude=None):
	return frappe.db.exists(
		"Leave Request",
		{
			"student": student,
			"status": ["in", [PENDING, APPROVED]],
			"from_date": ["<=", end],
			"to_date": [">=", start],
			"name": ["!=", exclude or ""],
		},
	)


@frappe.whitelist()
def cancel_request(name):
	"""The parent withdraws their own request while it is still waiting."""
	guardian = portal_guardian()
	doc = frappe.get_doc("Leave Request", name)
	if doc.guardian != guardian.name:
		frappe.throw("Ombi hili si lako.", frappe.PermissionError)
	if doc.status != PENDING:
		frappe.throw("Ombi linaloweza kufutwa ni lile linalosubiri uamuzi tu.")
	doc.status = CANCELLED
	doc.flags.from_portal = True
	doc.save(ignore_permissions=True)
	close_todos(doc)


def portal_requests(guardian):
	"""The guardian's requests for the portal page: no reason from anyone else, and nothing about other children."""
	return frappe.get_all(
		"Leave Request",
		filters={"guardian": guardian.name},
		fields=["name", "student_name", "from_date", "to_date", "school_days", "reason", "status", "decision_note", "decided_on", "attachment", "creation"],
		order_by="creation desc",
	)


# ---------- the school's side ----------


def deciders(doc):
	"""The class teacher of the student's class; without one, the Headmaster(s)."""
	teacher = frappe.db.get_value("Class", doc.get("class"), "class_teacher")
	user = teacher and frappe.db.get_value("Teacher", teacher, "user")
	if user:
		return [user]
	return [
		u
		for u in frappe.get_all("Has Role", filters={"role": "Headmaster", "parenttype": "User"}, pluck="parent", distinct=True)
		if frappe.db.get_value("User", u, "enabled")
	]


def notify_deciders(doc):
	from frappe.desk.form import assign_to

	users = deciders(doc)
	if not users:
		return
	assign_to._add(  # the parent (a website user) cannot read the request: the school is told on its behalf
		{
			"assign_to": users,
			"doctype": "Leave Request",
			"name": doc.name,
			"description": f"Leave request for {doc.student_name} ({doc.from_date} to {doc.to_date})",
			"date": doc.from_date,
		},
		ignore_permissions=True,
	)


def close_todos(doc):
	for todo in frappe.get_all(
		"ToDo", filters={"reference_type": "Leave Request", "reference_name": doc.name, "status": "Open"}, pluck="name"
	):
		frappe.db.set_value("ToDo", todo, "status", "Closed")


@frappe.whitelist()
def decide(name, decision, note=None):
	"""Approve or reject: the class teacher of the student's class, or the Headmaster / System Manager."""
	doc = frappe.get_doc("Leave Request", name)
	if not has_permission(doc, "write"):
		frappe.throw("Only the class teacher of this class or the Headmaster decides on this request", frappe.PermissionError)
	if decision not in (APPROVED, REJECTED):
		frappe.throw("Approve or reject")
	if doc.status != PENDING:
		frappe.throw(f"This request is already {doc.status}")
	doc.status = decision
	doc.decision_note = (note or "").strip() or None
	doc.decided_by = frappe.session.user
	doc.decided_on = now_datetime()
	doc.flags.deciding = True
	doc.save(ignore_permissions=True)
	if decision == APPROVED:
		excuse_attendance(doc)
	close_todos(doc)
	send_decision_sms(doc)
	return doc.status


@frappe.whitelist()
def withdraw(name, note=None):
	"""The Headmaster withdraws an approved leave: its attendance goes back to what it was."""
	frappe.only_for(DECIDER_ROLES)
	doc = frappe.get_doc("Leave Request", name)
	if doc.status != APPROVED:
		frappe.throw("Only an approved leave can be withdrawn")
	restore_attendance(doc)
	doc.status = CANCELLED
	doc.decision_note = (note or "").strip() or doc.decision_note
	doc.decided_by = frappe.session.user
	doc.decided_on = now_datetime()
	doc.flags.deciding = True
	doc.save(ignore_permissions=True)
	return doc.status


def excuse_attendance(doc):
	"""The school days of the leave already recorded Absent become Excused (and remember it); a child recorded
	Present or Late came to school, so those records stay as they are."""
	calendar = SchoolCalendar()
	changed = 0
	for r in frappe.get_all(
		"Attendance",
		filters={"student": doc.student, "date": ["between", [doc.from_date, doc.to_date]], "status": "Absent"},
		fields=["name", "date", "class"],
	):
		if not calendar.is_school_day(r.date, r["class"]):
			continue
		frappe.db.set_value(
			"Attendance", r.name, {"status": "Excused", "leave_request": doc.name, "status_before_leave": "Absent"}
		)
		changed += 1
	return changed


def restore_attendance(doc):
	"""Only what the leave changed goes back: records it excused that are still Excused return to Absent (a record
	corrected since, e.g. to Present, is left alone and just unlinked)."""
	for r in frappe.get_all("Attendance", filters={"leave_request": doc.name}, fields=["name", "status"]):
		values = {"leave_request": None, "status_before_leave": None}
		if r.status == "Excused":
			values["status"] = "Absent"
		frappe.db.set_value("Attendance", r.name, values)


def approved_leave_for(students, day):
	"""{student: leave request} of approved leaves covering the day."""
	return dict(
		frappe.get_all(
			"Leave Request",
			filters={"student": ["in", list(students) or [""]], "status": APPROVED, "from_date": ["<=", day], "to_date": [">=", day]},
			fields=["student", "name"],
			as_list=True,
		)
	)


def send_decision_sms(doc):
	from smart_school.sms import queue_leave_decision

	queue_leave_decision(doc)
