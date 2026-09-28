# Copyright (c) 2026, john daudi and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.utils import escape_html

from smart_school.reports import FULL_ACCESS_ROLES
from smart_school.risk_model import get_active_model

FEATURE_LABELS = {
	"average": "Term average",
	"trend": "Change in average since the term before",
	"no_previous_term": "No term before to compare with",
	"failed_subjects": "Subjects with F",
	"absence_rate": "Absence rate (late counts half, excused not at all)",
	"discipline_points": "Discipline points",
}


def execute(filters=None):
	"""How well the risk model predicts, in plain words first, then the numbers behind it."""
	frappe.only_for(FULL_ACCESS_ROLES)
	filters = frappe._dict(filters or {})
	name = filters.get("risk_model") or get_active_model() or latest_evaluated_model()
	if not name:
		return get_columns(), [], "No risk model has been trained yet."

	doc = frappe.get_doc("Risk Model", name)
	if not doc.metrics_json:
		return get_columns(), [], f"{escape_html(doc.name)}: {escape_html(doc.decision or doc.status)}"

	m = json.loads(doc.metrics_json)
	data = (
		overall_rows(doc, m)
		+ new_risk_rows(m["new_risk"])
		+ calibration_rows(m["model"]["calibration"])
		+ fairness_rows(m)
		+ ablation_rows(m.get("ablation") or [])
		+ coefficient_rows(doc)
		+ data_rows(doc)
	)
	return get_columns(), data, summary(doc, m), calibration_chart(m["model"]["calibration"]), cards(doc)


def latest_evaluated_model():
	return frappe.db.get_value(
		"Risk Model", {"status": ["in", ["Active", "Rejected", "Retired"]]}, "name", order_by="creation desc"
	)


def pct(value):
	return f"{value * 100:.1f}%" if value is not None else ""


def ci(pair, percent=False):
	if not pair:
		return ""
	low, high = pair
	return f"{low * 100:+.1f} to {high * 100:+.1f} points" if percent else f"{low:+.3f} to {high:+.3f}"


def row(section, measure, model="", rule="", difference="", note=""):
	return {
		"section": section,
		"measure": measure,
		"model": model,
		"rule": rule,
		"difference": difference,
		"note": note,
	}


def summary(doc, m):
	model, rule, new = m["model"], m["rule"], m["new_risk"]
	if doc.status == "Active":
		opening = f"<b>{escape_html(doc.name)} is in use.</b> It predicts better than the rule-based score."
	else:
		opening = f"<b>{escape_html(doc.name)} is not in use ({escape_html(doc.status)}).</b> {escape_html(doc.decision)}"
	worst = max((c["mean_predicted"] - c["observed"] for c in model["calibration"]), default=0)
	lines = [
		opening,
		f"Of the 10% of students it lists first each term, {pct(model['precision_top'])} really ended the next "
		f"term in Division IV/0 or with 3+ subjects with F (rule-based score: {pct(rule['precision_top'])}). "
		f"Those lists hold {pct(model['recall_top'])} of all students who fell (rule-based: {pct(rule['recall_top'])}).",
		f"Among students who were not at risk yet, its top 10% holds {pct(new['model']['recall_top'])} of those who "
		f"fell next term (rule-based: {pct(new['rule']['recall_top'])}): spotting a fall early is much harder.",
		"Its probabilities match what happened"
		+ (
			f", except in the middle where they are up to {worst * 100:.0f} points too high."
			if worst > 0.05
			else " closely."
		),
	]
	if model["fairness"].get("warning"):
		lines.append(
			"Precision or recall differs by more than 10 points between girls and boys (see Fairness); "
			"the groups are small, so this can be chance, but it is worth watching."
		)
	lines.append(
		f"Tested on {escape_html(doc.test_terms)} ({doc.test_rows} student-terms), "
		f"trained on {escape_html(doc.train_terms)} ({doc.train_rows} student-terms)."
	)
	return "<br>".join(lines)


def overall_rows(doc, m):
	model, rule, boot = m["model"], m["rule"], m["bootstrap"]
	confusion = lambda c: f"TP {c['tp']} · FP {c['fp']} · FN {c['fn']} · TN {c['tn']}"
	s = "All students"
	return [
		row(
			s,
			"AUC",
			f"{model['auc']:.3f}",
			f"{rule['auc']:.3f}",
			f"{model['auc'] - rule['auc']:+.3f} (95% CI {ci([boot['ci_low'], boot['ci_high']])})",
			"How often a student who fell is ranked above one who did not (0.5 = guessing, 1 = perfect)",
		),
		row(
			s,
			"Precision @ top 10%",
			pct(model["precision_top"]),
			pct(rule["precision_top"]),
			f"{(model['precision_top'] - rule['precision_top']) * 100:+.1f} points",
			"Of the 10% listed first each term, the share who really fell",
		),
		row(
			s,
			"Recall @ top 10%",
			pct(model["recall_top"]),
			pct(rule["recall_top"]),
			f"{(model['recall_top'] - rule['recall_top']) * 100:+.1f} points",
			"Of all who fell, the share in the top-10% lists",
		),
		row(s, "Confusion @ top 10%", confusion(model["confusion_top"]), confusion(rule["confusion_top"])),
		row(s, "Confusion @ probability 50%", confusion(model["confusion_at_half"]), note="Model only"),
		row(
			s,
			"Brier score",
			f"{model['brier']:.4f}",
			note="Average squared error of the probabilities (0 is perfect)",
		),
		row(s, "Students who fell (base rate)", pct(m["base_rate"]), note=f"{doc.test_positives} of {doc.test_rows}"),
		row(
			s,
			"Bootstrap",
			f"{boot['resamples']} resamples, seed {boot['seed']}",
			note=f"Students resampled ({boot['used']} usable)",
		),
	]


def new_risk_rows(new):
	s = "New risk"
	boot = new.get("bootstrap") or {}
	model_ci = lambda key: boot.get("model", {}).get(key)
	rule_ci = lambda key: boot.get("rule", {}).get(key)
	auc = lambda v: f"{v:.3f}" if v is not None else "-"
	rows = [
		row(
			s,
			"Students not at risk yet",
			str(new["rows"]),
			note=f"{new['positives']} of them fell the next term",
		),
		row(
			s,
			"AUC",
			f"{auc(new['model']['auc'])} (CI {ci(model_ci('auc')).replace('+', '')})",
			f"{auc(new['rule']['auc'])} (CI {ci(rule_ci('auc')).replace('+', '')})",
			f"95% CI {ci(boot.get('difference', {}).get('auc'))}",
		),
		row(
			s,
			"Precision @ top 10%",
			f"{pct(new['model']['precision_top'])} (CI {ci(model_ci('precision_top'), True).replace('+', '')})",
			f"{pct(new['rule']['precision_top'])} (CI {ci(rule_ci('precision_top'), True).replace('+', '')})",
			f"95% CI {ci(boot.get('difference', {}).get('precision_top'), True)}",
			"Top 10% taken within this group, per term",
		),
		row(s, "Recall @ top 10%", pct(new["model"]["recall_top"]), pct(new["rule"]["recall_top"])),
	]
	return rows


def calibration_rows(calibration):
	return [
		row(
			"Calibration",
			f"Decile {c['decile']}",
			f"predicted {c['mean_predicted'] * 100:.1f}%",
			note=f"observed {c['observed'] * 100:.1f}% of {c['students']} students",
		)
		for c in calibration
	]


def fairness_rows(m):
	rows = []
	model, rule = m["model"]["fairness"], m["rule"]["fairness"]
	for group, values in model["groups"].items():
		r = rule["groups"].get(group, {})
		rows.append(
			row(
				"Fairness",
				group,
				f"precision {pct(values['precision'])} · recall {pct(values['recall'])}",
				f"precision {pct(r.get('precision'))} · recall {pct(r.get('recall'))}",
				note=f"{values['students']} students, {values['positives']} fell; "
				f"listed: model {values['flagged']}, rule-based {r.get('flagged')}",
			)
		)
	rows.append(
		row(
			"Fairness",
			"Largest gap",
			f"precision {model.get('precision_gap', 0) * 100:.1f} · recall {model.get('recall_gap', 0) * 100:.1f} points",
			f"precision {rule.get('precision_gap', 0) * 100:.1f} · recall {rule.get('recall_gap', 0) * 100:.1f} points",
			note="Warning above 10 points" + (" (model: warning)" if model.get("warning") else ""),
		)
	)
	return rows


def ablation_rows(ablation):
	auc = lambda v, change: f"{v:.4f} ({change:+.4f})" if v is not None and change is not None else "-"
	return [
		row(
			"Ablation",
			f"Without: {FEATURE_LABELS.get(a['removed'], a['removed'])}",
			f"AUC {auc(a['auc'], a['change'])}",
			difference=f"New-risk AUC {auc(a.get('new_risk_auc'), a.get('new_risk_change'))}",
			note="Helps" if a.get("helps") else "Does not help (removing it lowers neither AUC by 0.005)",
		)
		for a in ablation
	]


def coefficient_rows(doc):
	rows = [
		row(
			"Coefficients",
			FEATURE_LABELS.get(c.feature, c.feature),
			f"{c.coefficient:+.3f}",
			note=f"per standard deviation ({c.scale:.3g}) around the training mean {c.mean:.3g}; "
			"positive raises the risk",
		)
		for c in doc.coefficients
	]
	rows.append(row("Coefficients", "Intercept", f"{doc.intercept:+.3f}"))
	return rows


def data_rows(doc):
	s = "Data"
	return [
		row(s, "Training terms (predicted)", doc.train_terms, note=f"{doc.train_rows} student-terms, {doc.train_positives} fell"),
		row(s, "Test terms (predicted)", doc.test_terms, note=f"{doc.test_rows} student-terms, {doc.test_positives} fell"),
		row(s, "Model in use trained on", f"{doc.final_rows} student-terms", note="Training and test terms together"),
		row(s, "Features", f"version {doc.feature_set_version}", note=doc.features),
		row(s, "Trained", str(doc.trained_on), note=doc.trained_by),
	]


def calibration_chart(calibration):
	return {
		"data": {
			"labels": [str(c["decile"]) for c in calibration],
			"datasets": [
				{"name": "Predicted %", "values": [round(c["mean_predicted"] * 100, 1) for c in calibration]},
				{"name": "Observed %", "values": [round(c["observed"] * 100, 1) for c in calibration]},
			],
		},
		"type": "line",
		"title": "Calibration by decile of predicted risk",
	}


def cards(doc):
	return [
		{"value": doc.status, "label": "Status", "datatype": "Data", "indicator": "Green" if doc.status == "Active" else "Orange"},
		{"value": round(doc.model_auc, 3), "label": "Model AUC", "datatype": "Float"},
		{"value": round(doc.rule_auc, 3), "label": "Rule-based AUC", "datatype": "Float"},
		{"value": round(doc.model_precision_top, 1), "label": "Model Precision @ 10%", "datatype": "Percent"},
		{"value": round(doc.model_new_risk_auc or 0, 3), "label": "New-Risk AUC", "datatype": "Float"},
	]


def get_columns():
	return [
		{"fieldname": "section", "label": "Section", "fieldtype": "Data", "width": 120},
		{"fieldname": "measure", "label": "Measure", "fieldtype": "Data", "width": 260},
		{"fieldname": "model", "label": "Model", "fieldtype": "Data", "width": 230},
		{"fieldname": "rule", "label": "Rule-based", "fieldtype": "Data", "width": 230},
		{"fieldname": "difference", "label": "Difference / 95% CI", "fieldtype": "Data", "width": 260},
		{"fieldname": "note", "label": "Notes", "fieldtype": "Data", "width": 380},
	]
