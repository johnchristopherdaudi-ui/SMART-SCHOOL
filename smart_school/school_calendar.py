"""The school calendar: which days are school days, and what the calendars (desk and parent portal) show.

A school day is a day inside a term, Monday to Friday (Saturday too when Smart School Settings says so), that no
School Event with "Is School Day" off covers (a holiday, a break) for the whole school or the class. A School Event
with "Is School Day" on makes a weekend day a school day (a make-up Saturday); it never cancels a holiday.
Events that repeat every year (the fixed national holidays) are read from their day and month.

Terms and exams are shown from their own dates, never copied: change a term or an exam and the calendars follow.

Attendance is counted on school days only, by one function (count_attendance) used by the attendance reports,
the parent dashboard, the report card, the risk score and the risk model. A school day without a record is not
counted as absence: it lowers the attendance completeness instead (days with a record / school days)."""

from datetime import date, timedelta

import frappe
from frappe.utils import add_days, cint, flt, getdate, today

EVENT_TYPES = (
	"Term Opening",
	"Term Closing",
	"Midterm Break",
	"Public Holiday",
	"Exam Period",
	"Parents Meeting",
	"Sports Day",
	"Graduation",
	"Other",
)
ALL_SCHOOL = "All School"
STATUSES = ("Present", "Absent", "Late", "Excused")

# Tanzania's national holidays on fixed dates. Eid, Easter and Maulid move: the Headmaster adds them each year.
FIXED_HOLIDAYS = (
	("Mwaka Mpya", 1, 1),
	("Siku ya Mapinduzi ya Zanzibar", 1, 12),
	("Siku ya Karume", 4, 7),
	("Siku ya Muungano", 4, 26),
	("Siku ya Wafanyakazi", 5, 1),
	("Saba Saba", 7, 7),
	("Nane Nane (Siku ya Wakulima)", 8, 8),
	("Siku ya Kumbukumbu ya Mwalimu Nyerere", 10, 14),
	("Siku ya Uhuru", 12, 9),
	("Krismasi", 12, 25),
	("Siku ya Kupeana Zawadi", 12, 26),
)

COLORS = {
	"Public Holiday": "#e03131",
	"Midterm Break": "#f08c00",
	"Exam Period": "#7048e8",
	"Exam": "#7048e8",
	"Term": "#2f9e44",
	"Term Opening": "#2f9e44",
	"Term Closing": "#2f9e44",
	"Parents Meeting": "#1c7ed6",
}
DEFAULT_COLOR = "#495057"


def date_range(start, end):
	day, end = getdate(start), getdate(end)
	while day <= end:
		yield day
		day += timedelta(days=1)


class SchoolCalendar:
	"""Loads the events once; answers "is this a school day for this class?" for many dates (risk model, reports)."""

	def __init__(self):
		self.saturday = cint(frappe.db.get_single_value("Smart School Settings", "saturday_is_school_day"))
		self.terms = frappe.get_all(
			"Term", fields=["name", "start_date", "end_date"], filters={"start_date": ["is", "set"]}, order_by="start_date asc"
		)
		self.events = load_events()
		self._days = {}  # class (or None) -> {date: school day?} built lazily per year

	def term_of(self, day):
		day = getdate(day)
		for t in self.terms:
			if getdate(t.start_date) <= day <= getdate(t.end_date):
				return t
		return None

	def is_school_day(self, day, class_name=None):
		day = getdate(day)
		if not self.term_of(day):
			return False
		off, on = self.marks(day.year, class_name)
		if day in off:
			return False
		return day.weekday() < 5 or (day.weekday() == 5 and self.saturday) or day in on

	def marks(self, year, class_name):
		"""(days off, extra school days) in a year for a class, from the events that apply to it."""
		key = (year, class_name)
		if key not in self._days:
			off, on = set(), set()
			for event in self.events:
				if not applies(event, class_name):
					continue
				for start, end in occurrences(event, date(year, 1, 1), date(year, 12, 31)):
					for day in date_range(start, end):
						(on if event.is_school_day else off).add(day)
			self._days[key] = (off, on)
		return self._days[key]

	def why_not(self, day, class_name=None):
		"""None for a school day; otherwise why not: outside the terms, a holiday or break (its title), a weekend."""
		day = getdate(day)
		if self.is_school_day(day, class_name):
			return None
		if not self.term_of(day):
			return "outside the terms"
		titles = [
			e.title
			for e in self.events
			if not e.is_school_day
			and applies(e, class_name)
			and any(first <= day <= last for first, last in occurrences(e, day, day))
		]
		if titles:
			return ", ".join(titles)
		return "Saturday" if day.weekday() == 5 else "Sunday"

	def school_days(self, start, end, class_name=None):
		return [d for d in date_range(start, end) if self.is_school_day(d, class_name)]

	def term_school_days(self, term, class_name=None, until=None):
		"""School days of a term up to `until` (default today): what attendance could have been taken on."""
		term = frappe._dict(term) if isinstance(term, dict) else term
		if isinstance(term, str):
			term = next((t for t in self.terms if t.name == term), None)
		if not term:
			return []
		end = min(getdate(term.end_date), getdate(until or today()))
		return self.school_days(term.start_date, end, class_name)


def load_events():
	events = frappe.get_all(
		"School Event",
		fields=[
			"name",
			"title",
			"event_type",
			"start_date",
			"end_date",
			"is_school_day",
			"audience",
			"show_on_portal",
			"repeat_every_year",
			"description",
		],
	)
	classes = {}
	for row in frappe.get_all(
		"School Event Class", filters={"parenttype": "School Event"}, fields=["parent", "class"]
	):
		classes.setdefault(row.parent, set()).add(row["class"])
	for e in events:
		e.classes = classes.get(e.name, set())
	return events


def applies(event, class_name=None, class_names=None):
	"""A whole-school event applies to everyone; a class event to its classes only."""
	if event.audience != "Specific Classes":
		return True
	wanted = set(class_names or []) | ({class_name} if class_name else set())
	return bool(event.classes & wanted)


def occurrences(event, start, end):
	"""(start, end) of each time the event happens between start and end: once, or every year on its dates."""
	start, end = getdate(start), getdate(end)
	first, last = getdate(event.start_date), getdate(event.end_date or event.start_date)
	if not event.repeat_every_year:
		if first <= end and last >= start:
			yield first, last
		return
	length = (last - first).days
	for year in range(start.year - 1, end.year + 1):
		try:
			begin = first.replace(year=year)
		except ValueError:  # 29 February in a year without it
			continue
		finish = begin + timedelta(days=length)
		if begin <= end and finish >= start:
			yield begin, finish


# ---------- attendance ----------


def count_attendance(records, calendar=None):
	"""Counts of attendance records (with date, status and class) on school days only; records on other days
	(a holiday, a weekend, outside the terms) are left out and counted apart. Absence rate: Absent fully, Late
	half, Excused not at all, over the days recorded; attended rate: Present and Late over the days recorded."""
	calendar = calendar or SchoolCalendar()
	counts = {s: 0 for s in STATUSES}
	not_counted = 0
	for r in records:
		if calendar.is_school_day(r.date, r.get("class")):
			counts[r.status] = counts.get(r.status, 0) + 1
		else:
			not_counted += 1
	days = sum(counts.values())
	return frappe._dict(
		days=days,
		present=counts["Present"],
		absent=counts["Absent"],
		late=counts["Late"],
		excused=counts["Excused"],
		not_counted=not_counted,
		absence_rate=(counts["Absent"] + 0.5 * counts["Late"]) / days * 100 if days else 0.0,
		attended_rate=(counts["Present"] + counts["Late"]) / days * 100 if days else None,
	)


def attendance_records(filters):
	return frappe.get_all("Attendance", filters=filters, fields=["student", "date", "status", "class", "term"])


def completeness(class_name, term, calendar=None, until=None):
	"""Share of a class's school days in a term (so far) with attendance taken: days with at least one record /
	school days. None before the term's first school day."""
	calendar = calendar or SchoolCalendar()
	days = calendar.term_school_days(term, class_name, until)
	if not days:
		return None
	recorded = {
		getdate(d)
		for d in frappe.get_all(
			"Attendance", filters={"class": class_name, "term": term}, pluck="date", distinct=True
		)
	}
	return len(recorded & set(days)) / len(days) * 100


def get_completeness_min():
	return flt(frappe.db.get_single_value("Smart School Settings", "attendance_completeness_min")) or 80


# ---------- what the calendars show ----------


def calendar_items(start, end, class_names=None, portal=False):
	"""Events (repeats unfolded), term openings and closings, and exams with dates, between start and end.
	portal: only events shown on the portal, and only those (and exams) for the given classes."""
	start, end = getdate(start), getdate(end)
	items = []
	for event in load_events():
		if portal and not event.show_on_portal:
			continue
		if class_names is not None and not applies(event, class_names=class_names):
			continue
		for first, last in occurrences(event, start, end):
			items.append(
				frappe._dict(
					kind=event.event_type,
					title=event.title,
					start=first,
					end=last,
					is_school_day=event.is_school_day,
					description=event.description,
					doctype="School Event",
					name=event.name,
					derived=bool(event.repeat_every_year),
				)
			)
	for term in frappe.get_all("Term", fields=["name", "start_date", "end_date"]):
		for day, what in ((term.start_date, "opens"), (term.end_date, "closes")):
			if day and start <= getdate(day) <= end:
				items.append(
					frappe._dict(
						kind="Term",
						what=what,
						title=f"{term.name} {what}",
						term=term.name,
						start=getdate(day),
						end=getdate(day),
						is_school_day=1,
						doctype="Term",
						name=term.name,
						derived=True,
					)
				)
	exam_filters = {"start_date": ["<=", end], "end_date": [">=", start]}
	if class_names is not None:
		exam_filters["class"] = ["in", list(class_names) or [""]]
	for exam in frappe.get_all(
		"Exam", filters=exam_filters, fields=["name", "exam_name", "class", "start_date", "end_date"]
	):
		items.append(
			frappe._dict(
				kind="Exam",
				title=f"{exam.exam_name} ({exam['class']})",
				exam_name=exam.exam_name,
				class_name=exam["class"],
				start=getdate(exam.start_date),
				end=getdate(exam.end_date or exam.start_date),
				is_school_day=1,
				doctype="Exam",
				name=exam.name,
				derived=True,
			)
		)
	return sorted(items, key=lambda i: (i.start, i.end, i.title))


@frappe.whitelist()
def get_calendar_events(start, end, filters=None, **kwargs):
	"""Desk calendar of School Event: its events plus the terms and exams (which open their own forms)."""
	frappe.has_permission("School Event", "read", throw=True)
	events = []
	for item in calendar_items(getdate(start), getdate(end)):
		events.append(
			{
				"name": item.name,
				"doctype": item.doctype,
				"title": item.title,
				"start_date": str(item.start),
				"end_date": str(item.end),
				"all_day": 1,
				"color": COLORS.get(item.kind, DEFAULT_COLOR),
				"derived": 1 if item.derived else 0,
				"tooltip": f"{item.kind}" + ("" if item.is_school_day else " (no school)"),
			}
		)
	return events
