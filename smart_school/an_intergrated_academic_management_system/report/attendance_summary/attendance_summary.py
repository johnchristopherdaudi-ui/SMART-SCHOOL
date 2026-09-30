# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt, getdate

from smart_school.reports import get_allowed_classes
from smart_school.school_calendar import STATUSES, SchoolCalendar, count_attendance

STATUS_FIELDS = {s: s.lower() for s in STATUSES}


def execute(filters=None):
	"""Attendance of a term on school days (see smart_school.school_calendar), per class or per student.
	Absence rate: Absent fully, Late half, Excused not at all, over the days recorded (like the risk score).
	Completeness: the school days so far with attendance taken (a class: days with any record; a student: days
	with their record). Records on days that are not school days are not counted, only shown."""
	filters = frappe._dict(filters or {})
	classes = get_allowed_classes(filters.get("class"))
	by_student = filters.get("group_by") == "Student"
	calendar = SchoolCalendar()

	records = frappe.get_all(
		"Attendance",
		filters={"term": filters.term, "class": ["in", classes or [""]]},
		fields=["student", "class", "date", "status"],
	)
	groups = {}
	for r in records:
		key = (r["class"], r.student) if by_student else (r["class"],)
		groups.setdefault(key, []).append(r)

	school_days = {c: set(calendar.term_school_days(filters.term, c)) for c in {k[0] for k in groups}}
	names = dict(frappe.get_all("Student", fields=["name", "full_name"], as_list=True)) if by_student else {}
	data = []
	for key, rows in sorted(groups.items()):
		counts = count_attendance(rows, calendar)
		days = school_days.get(key[0]) or set()
		taken = {getdate(r.date) for r in rows} & days
		row = {
			"class": key[0],
			"school_days": len(days),
			"days": counts.days,
			"completeness": flt(len(taken) / len(days) * 100, 1) if days else None,
			"absence_rate": flt(counts.absence_rate, 1),
			"not_counted": counts.not_counted,
		}
		if by_student:
			row.update({"student": key[1], "student_name": names.get(key[1])})
		row.update({field: counts[field] for field in STATUS_FIELDS.values()})
		data.append(row)

	return get_columns(by_student), data


def get_columns(by_student):
	columns = [
		{"fieldname": "class", "label": "Class", "fieldtype": "Link", "options": "Class", "width": 100}
	]
	if by_student:
		columns += [
			{
				"fieldname": "student",
				"label": "Student",
				"fieldtype": "Link",
				"options": "Student",
				"width": 140,
			},
			{"fieldname": "student_name", "label": "Student Name", "fieldtype": "Data", "width": 190},
		]
	columns += [
		{"fieldname": "school_days", "label": "School Days So Far", "fieldtype": "Int", "width": 130},
		{"fieldname": "days", "label": "Days Recorded", "fieldtype": "Int", "width": 110},
		{"fieldname": "completeness", "label": "Completeness %", "fieldtype": "Percent", "width": 120},
	]
	columns += [{"fieldname": f, "label": s, "fieldtype": "Int", "width": 90} for s, f in STATUS_FIELDS.items()]
	columns += [
		{"fieldname": "absence_rate", "label": "Absence Rate %", "fieldtype": "Percent", "width": 120},
		{"fieldname": "not_counted", "label": "Not School Days", "fieldtype": "Int", "width": 120},
	]
	return columns
