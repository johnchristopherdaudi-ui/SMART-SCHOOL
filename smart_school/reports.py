"""Shared helpers for the Script Reports, number cards and dashboard charts."""

import frappe
from frappe.utils import flt, getdate, today

from smart_school.fees import get_fee_statement
from smart_school.tasks import get_current_term

FULL_ACCESS_ROLES = ("Headmaster", "System Manager")
FEE_ROLES = ("Accountant", "Headmaster", "System Manager")
ACADEMIC_ROLES = ("Teacher", "Headmaster", "System Manager")


def get_teacher_scope():
	"""None means full access (Headmaster / System Manager). A Teacher gets {class: {subjects}} from their
	Teacher Subject Assignments, so academic reports show only those classes and subjects."""
	if frappe.session.user == "Administrator" or set(FULL_ACCESS_ROLES) & set(frappe.get_roles()):
		return None

	scope = {}
	teacher = frappe.db.get_value("Teacher", {"user": frappe.session.user}, "name")
	if teacher:
		for row in frappe.get_all(
			"Teacher Subject Assignment",
			filters={"parenttype": "Teacher", "parent": teacher},
			fields=["class", "subject"],
		):
			scope.setdefault(row["class"], set()).add(row.subject)
	return scope


def get_allowed_classes(class_name=None):
	"""Classes this user may report on, optionally narrowed to one class (refused if not allowed)."""
	frappe.only_for(ACADEMIC_ROLES)
	scope = get_teacher_scope()
	if class_name:
		if scope is not None and class_name not in scope:
			frappe.throw(f"You are not assigned to teach in {class_name}", frappe.PermissionError)
		return [class_name]

	classes = frappe.get_all("Class", pluck="name", order_by="level asc")
	return classes if scope is None else [c for c in classes if c in scope]


@frappe.whitelist()
def get_default_term():
	"""The term running today (start_date <= today <= end_date): the default Term filter of the reports."""
	frappe.only_for(ACADEMIC_ROLES + FEE_ROLES)
	return frappe.db.get_value("Term", {"start_date": ["<=", today()], "end_date": [">=", today()]}, "name")


def get_current_term_name():
	term = get_current_term()
	return term.name if term else None


# ---------- number cards ----------


@frappe.whitelist()
def get_fees_collected_this_term(filters=None):
	frappe.only_for(FEE_ROLES)
	term = get_current_term_name()
	total = (
		frappe.get_all(
			"Fee Payment", filters={"term": term, "docstatus": 1}, fields=["sum(amount_paid) as total"]
		)[0].total
		if term
		else 0
	)
	return {"value": flt(total), "fieldtype": "Currency"}


@frappe.whitelist()
def get_outstanding_fees(filters=None):
	"""Every student's balance: students who left still owe what was due before they left."""
	frappe.only_for(FEE_ROLES)
	students = frappe.get_all("Student", pluck="name")
	return {"value": sum(get_fee_statement(s).balance for s in students), "fieldtype": "Currency"}


# ---------- early warning ----------

EARLY_WARNING_ROLES = ("Teacher", "Headmaster", "System Manager")
EMERGING = "Wanaoanza kushuka"  # not at risk in the term the prediction starts from, but the model is high
ALREADY_AT_RISK = "Walio tayari hatarini"
HIGH_LEVELS = ("Medium", "High")


def get_early_warning_classes(class_name=None):
	"""None means every class (Headmaster / System Manager). A Teacher sees only the classes they are the
	class teacher of; any other teacher is refused."""
	frappe.only_for(EARLY_WARNING_ROLES)
	if frappe.session.user == "Administrator" or set(FULL_ACCESS_ROLES) & set(frappe.get_roles()):
		return [class_name] if class_name else None

	teacher = frappe.db.get_value("Teacher", {"user": frappe.session.user}, "name")
	classes = frappe.get_all("Class", filters={"class_teacher": teacher}, pluck="name") if teacher else []
	if not classes:
		frappe.throw("Only the Headmaster and class teachers can see early warnings", frappe.PermissionError)
	if class_name and class_name not in classes:
		frappe.throw(f"You are not the class teacher of {class_name}", frappe.PermissionError)
	return [class_name] if class_name else classes


def get_early_warning_section(prediction):
	if prediction.at_risk_now:
		return ALREADY_AT_RISK
	if prediction.probability_level in HIGH_LEVELS:
		return EMERGING
	return None


@frappe.whitelist()
def get_emerging_risk_count(filters=None):
	"""Number card: students not at risk yet whom the model in use rates Medium or High for next term."""
	frappe.only_for(FULL_ACCESS_ROLES)
	from smart_school.risk_model import get_active_model, get_prediction_term

	model = get_active_model()
	term = model and get_prediction_term(model)
	count = 0
	if term:
		count = frappe.db.count(
			"Risk Prediction",
			{"risk_model": model, "term": term, "at_risk_now": 0, "probability_level": ["in", HIGH_LEVELS]},
		)
	return {"value": count, "fieldtype": "Int"}


# ---------- dashboard chart data ----------


def get_division_distribution():
	term = get_current_term_name()
	classes = get_allowed_classes()
	divisions = frappe.get_all("Division Grading", pluck="division", order_by="minimum_points asc") + [
		"Incomplete"
	]
	counts = dict.fromkeys(divisions, 0)
	for division in frappe.get_all(
		"Student Term Result", filters={"term": term, "class": ["in", classes or [""]]}, pluck="division"
	):
		counts[division] = counts.get(division, 0) + 1
	return {
		"labels": list(counts),
		"datasets": [{"name": f"Divisions ({term})", "values": list(counts.values())}],
	}


def get_fee_collection_by_term():
	frappe.only_for(FEE_ROLES)
	rows = frappe.db.sql(
		"""select fp.term, sum(fp.amount_paid) as total
        from `tabFee Payment` fp join `tabTerm` t on t.name = fp.term
        where fp.docstatus = 1 group by fp.term order by min(t.start_date)""",
		as_dict=True,
	)
	return {
		"labels": [r.term for r in rows],
		"datasets": [{"name": "Collected", "values": [flt(r.total) for r in rows]}],
	}


def get_absence_rate_by_class():
	"""Absence rate on school days (Absent fully, Late half, Excused not at all, like the risk score)."""
	from smart_school.school_calendar import SchoolCalendar, attendance_records, count_attendance

	term = get_current_term_name()
	calendar = SchoolCalendar()
	labels, values = [], []
	for class_name in get_allowed_classes():
		counts = count_attendance(attendance_records({"term": term, "class": class_name}), calendar)
		labels.append(class_name)
		values.append(flt(counts.absence_rate, 1))
	return {"labels": labels, "datasets": [{"name": f"Absence rate % ({term})", "values": values}]}


@frappe.whitelist()
def get_attendance_completeness(filters=None):
	"""Number card: of the current term's school days so far, the share with attendance taken, over all classes
	(each class's school days counted)."""
	from smart_school.school_calendar import SchoolCalendar

	frappe.only_for(("Headmaster", "System Manager"))
	term = get_current_term_name()
	calendar = SchoolCalendar()
	school_days = recorded = 0
	for class_name in frappe.get_all("Class", pluck="name"):
		days = set(calendar.term_school_days(term, class_name)) if term else set()
		if not days:
			continue
		taken = {
			getdate(d)
			for d in frappe.get_all(
				"Attendance", filters={"term": term, "class": class_name}, pluck="date", distinct=True
			)
		}
		school_days += len(days)
		recorded += len(taken & days)
	return {"value": flt(recorded / school_days * 100, 1) if school_days else 0, "fieldtype": "Percent"}
