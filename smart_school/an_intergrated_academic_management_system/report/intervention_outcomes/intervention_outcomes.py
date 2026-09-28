# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import escape_html

from smart_school.intervention_outcomes import (
	BOOTSTRAP_RESAMPLES,
	COVARIATES,
	DESIGNS,
	analyse,
	collect_rows,
	get_min_sample,
)
from smart_school.reports import FULL_ACCESS_ROLES

OUTCOMES = {
	"positive": ("At risk in term T", "percentage points"),
	"change": ("Change in average from t to T", "points"),
}

WARNING = (
	'<div style="border:1px solid #e0a800;background:#fff8e1;padding:10px 12px;border-radius:6px">'
	"<b>An observational comparison, not proof that interventions work.</b> Students are not chosen for an "
	"intervention at random: the school picks those who worry it most (<i>selection bias</i>), and students who "
	"did unusually badly tend to do better the next term anyway (<i>regression to the mean</i>). Comparing them "
	"with students of the same term and the same risk decile who had no intervention reduces both, but cannot "
	"remove differences the risk score does not see."
	"</div>"
)


def execute(filters=None):
	frappe.only_for(FULL_ACCESS_ROLES)
	rows, basis = collect_rows()
	if not rows:
		return get_columns(), [], WARNING + "<p>No finished term has interventions with results yet.</p>"

	min_sample = get_min_sample()
	result = analyse(rows, min_sample)
	data = []
	for design, label in DESIGNS.items():
		d = result["designs"][design]
		for outcome, (measure, unit) in OUTCOMES.items():
			o = d["outcomes"][outcome]
			data.append(
				row(
					label,
					measure,
					treated=f"{number(o['treated_mean'], outcome)} (n={d['counts']['treated']})",
					comparison=f"{number(o['comparison_mean'], outcome)} (n={d['counts']['comparison']})",
					difference=difference(o["effect"], o["ci"], unit),
					raw=signed(o["raw"], unit),
					note=left_out_note(d["counts"]),
				)
			)

	for design, label in DESIGNS.items():
		for covariate, name in COVARIATES.items():
			b = result["balance"][design][covariate]
			scale = 100 if covariate == "absence_t" else 1
			data.append(
				row(
					"Balance",
					f"{name} ({label.split(' (')[0]})",
					treated=scaled(b["treated"], scale),
					comparison=f"before {scaled(b['comparison_before'], scale)} · after {scaled(b['comparison_after'], scale)}",
					note="Comparison after matching is weighted like the treated students across strata",
				)
			)

	for intervention_type, t in result["types"].items():
		if not t["enough"]:
			data.append(
				row(
					"By type (per-protocol)",
					intervention_type,
					treated=f"n={t['counts']['treated']}",
					note=f"Fewer than {min_sample} matched students: no estimate",
				)
			)
			continue
		for outcome, (measure, unit) in OUTCOMES.items():
			o = t["outcomes"][outcome]
			data.append(
				row(
					"By type (per-protocol)",
					f"{intervention_type}: {measure}",
					treated=f"n={t['counts']['treated']}",
					difference=difference(o["effect"], o["ci"], unit),
					note="Comparing many types can show differences by chance",
				)
			)
	return get_columns(), data, message(basis, rows)


def message(basis, rows):
	terms = list(dict.fromkeys(r.term for r in rows))  # in term order, as collect_rows goes
	return (
		WARNING
		+ "<p style='margin-top:10px'><b>Per-protocol</b> compares students whose intervention was completed; "
		"<b>intention-to-treat</b> compares every student given an intervention, completed or not. "
		"Intention-to-treat answers \"what happens when the school decides to act\" and is usually smaller; "
		"per-protocol can look better because students who complete may differ from those who do not.</p>"
		f"<p>Risk from the term before each term (t), by the {escape_html(basis)}, in deciles within each term. "
		f"Terms: {escape_html(', '.join(terms))}. 95% intervals: {BOOTSTRAP_RESAMPLES:,} bootstrap resamples of "
		"students.</p>"
	)


def row(section, measure, treated="", comparison="", difference="", raw="", note=""):
	return {
		"section": section,
		"measure": measure,
		"treated": treated,
		"comparison": comparison,
		"difference": difference,
		"raw": raw,
		"note": note,
	}


def number(value, outcome):
	if value is None:
		return "-"
	return f"{value:.1f}%" if outcome == "positive" else f"{value:+.1f}"


def scaled(value, scale):
	return "-" if value is None else (f"{value * scale:.1f}%" if scale == 100 else f"{value:.1f}")


def signed(value, unit):
	return "-" if value is None else f"{value:+.1f} {unit}"


def difference(effect, ci, unit):
	if effect is None:
		return "-"
	interval = f" (95% CI {ci[0]:+.1f} to {ci[1]:+.1f})" if ci else ""
	return f"{effect:+.1f} {unit}{interval}"


def left_out_note(counts):
	if not counts["treated_left_out"]:
		return ""
	return f"{counts['treated_left_out']} treated students had no comparison student in their stratum and are left out"


def get_columns():
	return [
		{"fieldname": "section", "label": "Section", "fieldtype": "Data", "width": 230},
		{"fieldname": "measure", "label": "Measure", "fieldtype": "Data", "width": 260},
		{"fieldname": "treated", "label": "With Intervention", "fieldtype": "Data", "width": 150},
		{"fieldname": "comparison", "label": "Matched Comparison", "fieldtype": "Data", "width": 210},
		{"fieldname": "difference", "label": "Difference (95% CI)", "fieldtype": "Data", "width": 280},
		{"fieldname": "raw", "label": "Raw Difference (No Matching)", "fieldtype": "Data", "width": 220},
		{"fieldname": "note", "label": "Notes", "fieldtype": "Data", "width": 330},
	]
