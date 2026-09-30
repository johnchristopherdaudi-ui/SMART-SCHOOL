"""Intervention outcomes: an observational comparison, not proof of cause.

For every finished term T with interventions, each student with results in T and in the term before (t) gets the
risk of term t (the Active model's probability, else the rule-based score), placed in a decile within T. Students
with an intervention in T are compared with students of the same term and decile who had none (matching), on:
- at risk in T (Division IV/0 or 3+ subjects with F), in percentage points;
- change in average from t to T, in points.

Two estimates:
- per-protocol: students whose intervention was Completed (those with only other statuses are left out);
- intention-to-treat: every student with an intervention in T, whatever its status.
Each is the difference between treated and comparison students within a stratum (term x decile), averaged with
the treated counts as weights. Treated students in a stratum without comparison students are left out and
counted. 95% intervals come from 1,000 bootstrap resamples of students."""

import numpy as np

import frappe
from frappe.utils import cint, flt

from smart_school.risk_model import SchoolData, get_active_model, load_model, predict
from smart_school.tasks import get_risk_score

DECILES = 10
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 42
COVARIATES = {"avg_t": "Average in term t", "absence_t": "Absence rate in term t"}
DESIGNS = {"per_protocol": "Per-protocol (Completed)", "itt": "Intention-to-treat (all interventions)"}


def collect_rows(data=None):
	"""(rows, risk basis). One row per student and finished term T that had interventions in the school."""
	data = data or SchoolData()
	finished = data.finished_terms()
	interventions = {}
	for i in frappe.get_all(
		"Student Intervention",
		filters={"term": ["in", [t.name for t in finished] or [""]]},
		fields=["student", "term", "status", "intervention_type"],
	):
		interventions.setdefault((i.student, i.term), []).append(i)
	terms_with_interventions = {term for _, term in interventions}

	model_name = get_active_model()
	model = load_model(model_name) if model_name else None
	settings = frappe.get_cached_doc("Smart School Settings")
	rows = []
	for term in finished:
		before = data.previous(term)
		if term.name not in terms_with_interventions or not before:
			continue
		for (student, term_name), result in data.results.items():
			if term_name != term.name or (student, before.name) not in data.results:
				continue
			positive = data.label(student, term)
			if positive is None:
				continue
			features = data.features(student, before)
			score = predict(model, features)[0] if model else get_risk_score(student, before, settings, data.calendar)[0]
			rows.append(
				frappe._dict(
					student=student,
					term=term.name,
					score=score,
					avg_t=features["average"],
					absence_t=features["absence_rate"],
					positive=positive,
					change=flt(result.average) - features["average"],
					interventions=interventions.get((student, term.name), []),
				)
			)
	assign_deciles(rows)
	basis = f"model {model_name}" if model_name else "rule-based risk score (no model in use)"
	return rows, basis


def assign_deciles(rows):
	by_term = {}
	for r in rows:
		by_term.setdefault(r.term, []).append(r)
	for term_rows in by_term.values():
		ranked = sorted(term_rows, key=lambda r: (r.score, r.student))
		for rank, r in enumerate(ranked):
			r.decile = rank * DECILES // len(ranked) + 1


def arm(row, design, intervention_type=None):
	"""1 treated, 0 comparison (no intervention at all in T), None left out."""
	if not row.interventions:
		return 0
	if design == "itt":
		return 1
	completed = [
		i
		for i in row.interventions
		if i.status == "Completed" and (not intervention_type or i.intervention_type == intervention_type)
	]
	return 1 if completed else None


class Design:
	"""The arrays of one comparison, so the estimate and its bootstrap are quick."""

	def __init__(self, rows, design, intervention_type=None):
		strata, students = {}, {}
		self.arms, self.strata, self.students, self.rows = [], [], [], []
		for r in rows:
			a = arm(r, design, intervention_type)
			if a is None:
				continue
			self.rows.append(r)
			self.arms.append(a)
			self.strata.append(strata.setdefault((r.term, r.decile), len(strata)))
			self.students.append(students.setdefault(r.student, len(students)))
		self.arms = np.array(self.arms)
		self.strata = np.array(self.strata, dtype=int)
		self.students = np.array(self.students, dtype=int)
		self.n_strata, self.n_students = len(strata), len(students)

	def values(self, outcome):
		if outcome == "positive":
			return np.array([r.positive * 100.0 for r in self.rows])
		return np.array([flt(r[outcome]) for r in self.rows])

	def sums(self, values, weights):
		treated, control = self.arms == 1, self.arms == 0
		count = lambda mask: np.bincount(self.strata[mask], weights=weights[mask], minlength=self.n_strata)
		total = lambda mask: np.bincount(
			self.strata[mask], weights=(weights * values)[mask], minlength=self.n_strata
		)
		return count(treated), count(control), total(treated), total(control)

	def estimate(self, values, weights=None):
		"""(effect, treated mean, matched comparison mean) over strata with both groups."""
		if not self.n_strata:
			return None, None, None
		weights = np.ones(len(self.rows)) if weights is None else weights
		wt, wc, st, sc = self.sums(values, weights)
		ok = (wt > 0) & (wc > 0)
		if not wt[ok].sum():
			return None, None, None
		treated_mean = st[ok] / wt[ok]
		comparison_mean = sc[ok] / wc[ok]
		share = wt[ok] / wt[ok].sum()
		return (
			float(((treated_mean - comparison_mean) * share).sum()),
			float((treated_mean * share).sum()),
			float((comparison_mean * share).sum()),
		)

	def counts(self):
		wt, wc, _, _ = self.sums(np.zeros(len(self.rows)), np.ones(len(self.rows)))
		ok = (wt > 0) & (wc > 0)
		return {
			"treated": int(wt[ok].sum()),
			"treated_left_out": int(wt[~ok].sum()),
			"comparison": int(wc[ok].sum()),
		}

	def raw(self, values):
		treated, control = values[self.arms == 1], values[self.arms == 0]
		if not len(treated) or not len(control):
			return None
		return float(treated.mean() - control.mean())

	def bootstrap(self, values):
		"""95% interval of the effect, resampling students (all their terms together)."""
		rng = np.random.default_rng(BOOTSTRAP_SEED)
		effects = []
		for _ in range(BOOTSTRAP_RESAMPLES):
			picked = np.bincount(rng.integers(0, self.n_students, self.n_students), minlength=self.n_students)
			effect = self.estimate(values, picked[self.students].astype(float))[0]
			if effect is not None:
				effects.append(effect)
		if not effects:
			return None
		low, high = np.percentile(effects, [2.5, 97.5])
		return [float(low), float(high)]

	def balance(self, covariate):
		"""Mean of a term-t covariate: treated; comparison before matching; comparison after (strata weights)."""
		values = np.array([flt(r[covariate]) for r in self.rows])
		_, treated_mean, matched = self.estimate(values)
		control = values[self.arms == 0]
		return {
			"treated": treated_mean,
			"comparison_before": float(control.mean()) if len(control) else None,
			"comparison_after": matched,
		}


def analyse(rows, min_sample=20):
	"""Everything the report shows, from collect_rows()."""
	result = {"designs": {}, "types": {}, "balance": {}}
	for design in DESIGNS:
		d = Design(rows, design)
		result["designs"][design] = {"counts": d.counts(), "outcomes": {}}
		for outcome in ("positive", "change"):
			values = d.values(outcome)
			effect, treated_mean, comparison_mean = d.estimate(values)
			result["designs"][design]["outcomes"][outcome] = {
				"effect": effect,
				"treated_mean": treated_mean,
				"comparison_mean": comparison_mean,
				"ci": d.bootstrap(values) if effect is not None else None,
				"raw": d.raw(values),
			}
		result["balance"][design] = {c: d.balance(c) for c in COVARIATES}

	types = sorted({i.intervention_type for r in rows for i in r.interventions if i.status == "Completed"})
	for intervention_type in types:
		d = Design(rows, "per_protocol", intervention_type)
		counts = d.counts()
		entry = {"counts": counts, "enough": counts["treated"] >= min_sample, "outcomes": {}}
		if entry["enough"]:
			for outcome in ("positive", "change"):
				values = d.values(outcome)
				effect, _, _ = d.estimate(values)
				entry["outcomes"][outcome] = {"effect": effect, "ci": d.bootstrap(values) if effect is not None else None}
		result["types"][intervention_type] = entry
	return result


def get_min_sample():
	return cint(frappe.db.get_single_value("Smart School Settings", "intervention_min_sample")) or 20
