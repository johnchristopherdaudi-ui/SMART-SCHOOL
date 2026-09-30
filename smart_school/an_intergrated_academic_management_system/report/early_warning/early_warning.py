# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import escape_html

from smart_school.reports import (
	ALREADY_AT_RISK,
	EMERGING,
	get_early_warning_classes,
	get_early_warning_section,
)
from smart_school.interventions import get_interventions_text
from smart_school.risk_model import get_active_model, get_prediction_term
from smart_school.school_calendar import SchoolCalendar, completeness, get_completeness_min
from smart_school.tasks import get_current_term

SECTION_ORDER = {EMERGING: 0, ALREADY_AT_RISK: 1}


def execute(filters=None):
	"""Students the model in use expects at risk next term, in two groups: those not at risk yet
	("Wanaoanza kushuka") and those already at risk. The Headmaster sees every class, a class teacher only
	their own. Without a model in use, the rule-based risk score is shown with the reason."""
	filters = frappe._dict(filters or {})
	classes = get_early_warning_classes(filters.get("class"))
	model = get_active_model()
	term = model and get_prediction_term(model)
	if not term:
		return rule_based(filters, classes)

	query = {"risk_model": model, "term": term}
	if classes is not None:
		query["class"] = ["in", classes]
	data = []
	for p in frappe.get_all(
		"Risk Prediction",
		filters=query,
		fields=[
			"student",
			"student_name",
			"class",
			"probability",
			"probability_level",
			"at_risk_now",
			"reasons",
			"rule_score",
			"rule_level",
			"feature_term",
		],
	):
		section = get_early_warning_section(p)
		if not section or filters.section and section != filters.section:
			continue
		if filters.level and p.probability_level != filters.level:
			continue
		reasons = (p.reasons or "").splitlines() + ["", "", ""]
		data.append(
			{
				"section": section,
				"student": p.student,
				"student_name": p.student_name,
				"class": p["class"],
				"probability": p.probability,
				"level": p.probability_level,
				"reason_1": reasons[0],
				"reason_2": reasons[1],
				"reason_3": reasons[2],
				"rule_score": p.rule_score,
				"rule_level": p.rule_level,
				"from_term": p.feature_term,
				"term": term,
			}
		)
	data.sort(key=lambda r: (SECTION_ORDER[r["section"]], -r["probability"], r["student_name"] or ""))
	add_interventions(data, term)

	from_term = data[0]["from_term"] if data else None
	message = (
		f"Chance of Division IV/0 or 3+ subjects with F in <b>{escape_html(term)}</b>, "
		f"from the results and attendance of {escape_html(from_term or 'the last term')} "
		f"(model {escape_html(model)}). The rule-based score of the same term is shown beside it."
	) + completeness_note({r["class"] for r in data}, from_term)
	summary = [
		{"value": sum(r["section"] == EMERGING for r in data), "label": EMERGING, "indicator": "Orange"},
		{"value": sum(r["section"] == ALREADY_AT_RISK for r in data), "label": ALREADY_AT_RISK, "indicator": "Red"},
	]
	return get_columns(), data, message, None, summary


def rule_based(filters, classes):
	"""No model in use: the daily rule-based risk score, and why there is no model."""
	last = frappe.get_all("Risk Model", fields=["name", "decision"], order_by="creation desc", limit=1)
	why = last[0].decision if last else "No risk model has been trained yet."
	query = {"status": "Active", "risk_level": ["is", "set"]}
	if classes is not None:
		query["current_class"] = ["in", classes]
	if filters.level:
		query["risk_level"] = filters.level
	data = [
		{
			"section": "Rule-based",
			"student": s.name,
			"student_name": s.full_name,
			"class": s.current_class,
			"rule_score": s.risk_score,
			"rule_level": s.risk_level,
		}
		for s in frappe.get_all(
			"Student",
			filters=query,
			fields=["name", "full_name", "current_class", "risk_score", "risk_level"],
			order_by="risk_score desc",
		)
		if s.risk_level in ("Medium", "High") or filters.level
	]
	current = get_current_term()
	for row in data:
		row["term"] = current and current.name
	if current:
		add_interventions(data, current.name)
	message = f"No prediction model is in use. {escape_html(why)} Showing the rule-based risk score."
	if current:
		message += completeness_note({r["class"] for r in data}, current.name)
	return get_columns(), data, message


def completeness_note(classes, term):
	"""A small warning for classes whose attendance was taken on too few of the term's school days: their
	absence rates (and so the risk) rest on few days."""
	if not term:
		return ""
	calendar = SchoolCalendar()
	minimum = get_completeness_min()
	low = []
	for class_name in sorted(c for c in classes if c):
		share = completeness(class_name, term, calendar)
		if share is not None and share < minimum:
			low.append(f"{escape_html(class_name)} {share:.0f}%")
	if not low:
		return ""
	return (
		f"<p class='text-muted small' style='margin-top:6px'>&#9888; Attendance in {escape_html(term)} was taken "
		f"on fewer than {minimum:g}% of the school days in: {', '.join(low)}. Absence there may be understated.</p>"
	)


def add_interventions(data, term):
	"""The "Hatua" column: this term's interventions of each student, with their status."""
	text = get_interventions_text([r["student"] for r in data], term)
	for row in data:
		row["interventions"] = text.get(row["student"], "")


def get_columns():
	reason = lambda n: {"fieldname": f"reason_{n}", "label": f"Reason {n}", "fieldtype": "Data", "width": 280}
	return [
		{"fieldname": "section", "label": "Group", "fieldtype": "Data", "width": 160},
		{"fieldname": "student", "label": "Student", "fieldtype": "Link", "options": "Student", "width": 140},
		{"fieldname": "student_name", "label": "Student Name", "fieldtype": "Data", "width": 190},
		{"fieldname": "class", "label": "Class", "fieldtype": "Link", "options": "Class", "width": 90},
		{"fieldname": "probability", "label": "Probability", "fieldtype": "Percent", "width": 100},
		{"fieldname": "level", "label": "Level", "fieldtype": "Data", "width": 80},
		reason(1),
		reason(2),
		reason(3),
		{"fieldname": "rule_score", "label": "Rule Score", "fieldtype": "Float", "precision": 1, "width": 100},
		{"fieldname": "rule_level", "label": "Rule Level", "fieldtype": "Data", "width": 90},
		{"fieldname": "interventions", "label": "Hatua", "fieldtype": "Data", "width": 240},
		{"fieldname": "add_intervention", "label": "", "fieldtype": "Data", "width": 110},
		{"fieldname": "from_term", "label": "From Results Of", "fieldtype": "Link", "options": "Term", "width": 130},
		{"fieldname": "term", "label": "Term", "fieldtype": "Link", "options": "Term", "width": 110},
	]
