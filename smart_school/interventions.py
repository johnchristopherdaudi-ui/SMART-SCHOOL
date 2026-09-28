"""Student interventions: what the school does for a student at risk, who does it, and when to follow up.

The Headmaster and System Manager see everything. A class teacher creates interventions for the students of their
class, reads them all and edits the ones they created. The staff member responsible for an intervention reads and
updates it, whatever the class. Nobody else (other teachers, accountants, parents) sees them."""

import frappe
from frappe.utils import now_datetime, today

from smart_school.reports import get_early_warning_section

FULL_ACCESS_ROLES = ("Headmaster", "System Manager")
STAFF_ROLES = ("Teacher", "Headmaster", "System Manager")
OPEN_STATUSES = ("Planned", "In Progress")
SNAPSHOT_FIELDS = (
	"probability",
	"probability_level",
	"rule_score",
	"rule_level",
	"early_warning_group",
	"reasons",
	"risk_model",
)


def has_full_access(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(FULL_ACCESS_ROLES))


def class_teacher_classes(user=None):
	teacher = frappe.db.get_value("Teacher", {"user": user or frappe.session.user}, "name")
	return frappe.get_all("Class", filters={"class_teacher": teacher}, pluck="name") if teacher else []


def get_permission_query(user=None):
	"""List filter for Student Intervention: all for Headmaster / System Manager; for a Teacher the ones they are
	responsible for and those of the classes they are class teacher of; nothing for anyone else."""
	user = user or frappe.session.user
	if has_full_access(user):
		return None
	if "Teacher" not in frappe.get_roles(user):
		return "1=0"
	conditions = [f"`tabStudent Intervention`.`responsible` = {frappe.db.escape(user)}"]
	classes = class_teacher_classes(user)
	if classes:
		conditions.append(
			f"`tabStudent Intervention`.`class` in ({', '.join(frappe.db.escape(c) for c in classes)})"
		)
	return "(" + " or ".join(conditions) + ")"


def has_permission(doc, ptype=None, user=None):
	"""Per document: see the module docstring. Returns False to refuse; the role permissions still apply."""
	user = user or frappe.session.user
	if has_full_access(user):
		return True
	if "Teacher" not in frappe.get_roles(user):
		return False
	if ptype == "delete":
		return False
	if doc.get("responsible") == user and ptype != "create":
		return True
	class_name = doc.get("class") or frappe.db.get_value("Student", doc.get("student"), "current_class")
	if class_name not in class_teacher_classes(user):
		return False
	if ptype in ("write", "submit", "cancel", "amend"):
		return doc.get("owner") in (None, user)  # a class teacher edits the interventions they created
	return True


def fill_snapshot(doc):
	"""What the Early Warning said about the student for this term when the intervention was made."""
	prediction = frappe.db.get_value(
		"Risk Prediction",
		{"student": doc.student, "term": doc.term},
		[
			"probability",
			"probability_level",
			"rule_score",
			"rule_level",
			"at_risk_now",
			"reasons",
			"risk_model",
			"feature_term",
		],
		as_dict=True,
	)
	if not prediction:
		return
	doc.update(
		{
			"probability": prediction.probability,
			"probability_level": prediction.probability_level,
			"rule_score": prediction.rule_score,
			"rule_level": prediction.rule_level,
			"early_warning_group": get_early_warning_section(prediction) or "",
			"reasons": prediction.reasons,
			"risk_model": prediction.risk_model,
			"baseline_term": doc.baseline_term or prediction.feature_term,
		}
	)


def previous_term(term):
	start = frappe.db.get_value("Term", term, "start_date")
	earlier = frappe.get_all(
		"Term", filters={"start_date": ["<", start]}, pluck="name", order_by="start_date desc", limit=1
	)
	return earlier[0] if earlier else None


@frappe.whitelist()
def create_from_early_warning(
	student, term, intervention_type, responsible, follow_up_date, start_date=None, description=None
):
	"""The "Weka hatua" button of the Early Warning report. Normal permissions apply: the Headmaster, or the
	class teacher of the student's class."""
	frappe.only_for(STAFF_ROLES)
	doc = frappe.get_doc(
		{
			"doctype": "Student Intervention",
			"student": student,
			"term": term,
			"source": "Early Warning",
			"intervention_type": intervention_type,
			"responsible": responsible,
			"start_date": start_date or today(),
			"follow_up_date": follow_up_date,
			"description": description,
			"status": "Planned",
		}
	).insert()
	return doc.name


def get_interventions_text(students, term):
	"""{student: "Counseling (In Progress); Parent Meeting (Planned)"} for the Early Warning report."""
	text = {}
	for i in frappe.get_all(
		"Student Intervention",
		filters={"student": ["in", list(students) or [""]], "term": term},
		fields=["student", "intervention_type", "status"],
		order_by="creation asc",
	):
		text.setdefault(i.student, []).append(f"{i.intervention_type} ({i.status})")
	return {student: "; ".join(parts) for student, parts in text.items()}


def send_follow_up_reminders():
	"""Daily: when the follow-up date has come, the responsible person gets a ToDo (and its notification), once
	per follow-up date."""
	from frappe.desk.form import assign_to

	for i in frappe.get_all(
		"Student Intervention",
		filters={
			"status": ["in", OPEN_STATUSES],
			"follow_up_date": ["<=", today()],
			"reminder_sent_on": ["is", "not set"],
			"responsible": ["is", "set"],
		},
		fields=["name", "responsible", "intervention_type", "student_name", "follow_up_date"],
	):
		assign_to.add(
			{
				"assign_to": [i.responsible],
				"doctype": "Student Intervention",
				"name": i.name,
				"description": f"Follow up: {i.intervention_type} for {i.student_name} "
				f"(due {frappe.utils.formatdate(i.follow_up_date)})",
				"date": i.follow_up_date,
			}
		)
		frappe.db.set_value("Student Intervention", i.name, "reminder_sent_on", now_datetime(), update_modified=False)


@frappe.whitelist()
def get_follow_ups_due(filters=None):
	"""Number card: open interventions whose follow-up date has come, among those this user may see."""
	frappe.only_for(STAFF_ROLES)
	due = frappe.get_list(
		"Student Intervention",
		filters={"status": ["in", OPEN_STATUSES], "follow_up_date": ["<=", today()]},
		pluck="name",
	)
	return {"value": len(due), "fieldtype": "Int"}


def check_responsible(user):
	if not user:
		return
	enabled, user_type = frappe.db.get_value("User", user, ["enabled", "user_type"]) or (0, None)
	if not enabled or user_type != "System User" or not set(frappe.get_roles(user)) & set(STAFF_ROLES):
		frappe.throw(f"{user} is not a member of staff and cannot be responsible for an intervention")


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def staff_user_query(doctype, txt, searchfield, start, page_len, filters):
	"""Users who can be responsible for an intervention: enabled staff (Teacher, Headmaster, System Manager)."""
	frappe.only_for(STAFF_ROLES)
	return frappe.db.sql(
		"""select distinct u.name, u.full_name from `tabUser` u
		join `tabHas Role` r on r.parent = u.name and r.parenttype = 'User'
		where u.enabled = 1 and u.user_type = 'System User' and r.role in %(roles)s
			and (u.name like %(txt)s or u.full_name like %(txt)s)
		order by u.full_name limit %(start)s, %(page_len)s""",
		{"roles": STAFF_ROLES, "txt": f"%{txt}%", "start": start, "page_len": page_len},
	)
