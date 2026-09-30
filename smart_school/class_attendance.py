"""Class attendance: who may record it, and the tool that records a whole class at once.

Attendance is kept by the class teacher of the student's class; the Headmaster and System Manager keep it for every
class. This holds on the doctype itself (list, form, API), not only in the tool.

The tool (desk page Class Attendance): pick a class and a date; every active student of the class starts as
Present, except those with a record for that day (shown as recorded) and those with an approved leave (Excused);
change the few who differ and save once. A day that is not a school day (weekend, holiday, break) is saved only
after a warning, and its records are not counted (smart_school.school_calendar). Future dates and days outside
the terms are refused."""

import frappe
from frappe.utils import getdate, today

from smart_school.interventions import class_teacher_classes
from smart_school.school_calendar import STATUSES, SchoolCalendar

FULL_ACCESS_ROLES = ("Headmaster", "System Manager")


def has_full_access(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(FULL_ACCESS_ROLES) & set(frappe.get_roles(user)))


# ---------- permissions on the Attendance doctype ----------


def get_permission_query(user=None):
	user = user or frappe.session.user
	if has_full_access(user):
		return None
	classes = class_teacher_classes(user) if "Teacher" in frappe.get_roles(user) else []
	if not classes:
		return "1=0"
	return "`tabAttendance`.`class` in ({})".format(", ".join(frappe.db.escape(c) for c in classes))


def has_permission(doc, ptype=None, user=None):
	"""A new record: the student's current class must be the teacher's. An existing one: the record's class (the class
	the student was in that day), so a class teacher can still correct a record after the student moved up."""
	user = user or frappe.session.user
	if has_full_access(user):
		return True
	if "Teacher" not in frappe.get_roles(user):
		return False
	classes = set(class_teacher_classes(user))
	student_class = frappe.db.get_value("Student", doc.get("student"), "current_class") if doc.get("student") else None
	if ptype == "create" or not doc.get("name") or doc.get("__islocal"):
		return student_class in classes
	return (doc.get("class") or student_class) in classes


def check_student(doc):
	"""Attendance.validate: a teacher cannot put a record on a student of another class (e.g. by changing it)."""
	if has_full_access() or not (doc.is_new() or doc.has_value_changed("student")):
		return
	if frappe.db.get_value("Student", doc.student, "current_class") not in class_teacher_classes():
		frappe.throw(f"You are not the class teacher of {doc.student}'s class", frappe.PermissionError)


# ---------- the tool ----------


def allowed_classes():
	if has_full_access():
		return frappe.get_all("Class", pluck="name", order_by="level asc, name asc")
	classes = class_teacher_classes() if "Teacher" in frappe.get_roles() else []
	if not classes:
		frappe.throw("Only class teachers, the Headmaster and the System Manager record attendance", frappe.PermissionError)
	return classes


def check_class_and_date(class_name, day):
	if class_name not in allowed_classes():
		frappe.throw(f"You are not the class teacher of {class_name}", frappe.PermissionError)
	day = getdate(day)
	if day > getdate(today()):
		frappe.throw("Attendance cannot be recorded for a day that has not come yet")
	calendar = SchoolCalendar()
	term = calendar.term_of(day)
	if not term:
		frappe.throw(f"{day} is not inside any term")
	return day, term, calendar


@frappe.whitelist()
def get_classes():
	return allowed_classes()


@frappe.whitelist()
def get_sheet(class_name, date):
	"""The class on a day: each active student with the status to show (recorded, leave, or Present)."""
	day, term, calendar = check_class_and_date(class_name, date)
	students = frappe.get_all(
		"Student",
		filters={"current_class": class_name, "status": "Active"},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)
	names = [s.name for s in students]
	recorded = {
		r.student: r.status
		for r in frappe.get_all(
			"Attendance", filters={"student": ["in", names or [""]], "date": day}, fields=["student", "status"]
		)
	}
	on_leave = approved_leave(names, day)
	rows = []
	for s in students:
		if s.name in recorded:
			status, source = recorded[s.name], "recorded"
		elif s.name in on_leave:
			status, source = "Excused", "leave"
		else:
			status, source = "Present", "default"
		rows.append({"student": s.name, "student_name": s.full_name, "status": status, "source": source})
	return {
		"class": class_name,
		"date": str(day),
		"term": term.name,
		"not_school_day": calendar.why_not(day, class_name),
		"students": rows,
		"statuses": list(STATUSES),
	}


def approved_leave(students, day):
	"""Students with an approved leave covering the day (Part 3: Leave Request)."""
	if not frappe.db.exists("DocType", "Leave Request"):
		return set()
	return set(
		frappe.get_all(
			"Leave Request",
			filters={
				"student": ["in", list(students) or [""]],
				"status": "Approved",
				"from_date": ["<=", day],
				"to_date": [">=", day],
			},
			pluck="student",
		)
	)


@frappe.whitelist()
def save_sheet(class_name, date, entries):
	"""Record the day for the class at once: new records are created, changed ones updated, unchanged ones kept."""
	day, term, _ = check_class_and_date(class_name, date)
	entries = frappe.parse_json(entries) if isinstance(entries, str) else entries
	members = set(frappe.get_all("Student", filters={"current_class": class_name, "status": "Active"}, pluck="name"))
	existing = {
		r.student: r
		for r in frappe.get_all(
			"Attendance", filters={"student": ["in", list(members) or [""]], "date": day}, fields=["name", "student", "status"]
		)
	}
	counts = {s: 0 for s in STATUSES}
	created = updated = 0
	for entry in entries:
		student, status = entry.get("student"), entry.get("status")
		if student not in members:
			frappe.throw(f"{student} is not an active student of {class_name}")
		if status not in STATUSES:
			frappe.throw(f"Unknown attendance status: {status}")
		counts[status] += 1
		if student in existing:
			if existing[student].status != status:
				doc = frappe.get_doc("Attendance", existing[student].name)
				doc.status = status
				doc.save()
				updated += 1
			continue
		frappe.get_doc(
			{"doctype": "Attendance", "student": student, "date": day, "class": class_name, "status": status}
		).insert()
		created += 1
	return {"created": created, "updated": updated, "counts": counts, "term": term.name}
