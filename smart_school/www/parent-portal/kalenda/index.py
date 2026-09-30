import calendar
import re
from datetime import date, timedelta

import frappe
from frappe.utils import add_days, getdate, today

from smart_school.portal_utils import get_children, get_notifications, get_portal_guardian
from smart_school.school_calendar import calendar_items

MONTHS = (
	"Januari",
	"Februari",
	"Machi",
	"Aprili",
	"Mei",
	"Juni",
	"Julai",
	"Agosti",
	"Septemba",
	"Oktoba",
	"Novemba",
	"Desemba",
)
WEEKDAYS = ("Jumatatu", "Jumanne", "Jumatano", "Alhamisi", "Ijumaa", "Jumamosi", "Jumapili")
WEEKDAYS_SHORT = ("Jtt", "Jnn", "Jtn", "Alh", "Iju", "Jmo", "Jpi")
KINDS = {
	"Term Opening": "Kufungua shule",
	"Term Closing": "Kufunga shule",
	"Midterm Break": "Mapumziko",
	"Public Holiday": "Sikukuu",
	"Exam Period": "Kipindi cha mitihani",
	"Parents Meeting": "Mkutano wa wazazi",
	"Sports Day": "Michezo",
	"Graduation": "Mahafali",
	"Other": "Tukio",
	"Exam": "Mtihani",
	"Term": "Muhula",
}
UPCOMING_DAYS = 60


def get_context(context):
	"""Kalenda ya Shule: the coming events for the parent's children (their classes), and one month at a time."""
	guardian = get_portal_guardian()
	children = get_children(guardian)
	classes = sorted({c.current_class for c in children if c.current_class})

	month = month_from(frappe.form_dict.get("mwezi"))
	first = month.replace(day=1)
	last = first.replace(day=calendar.monthrange(first.year, first.month)[1])

	start = getdate(today())
	context.upcoming = [described(i) for i in calendar_items(start, add_days(start, UPCOMING_DAYS), classes, portal=True)]
	month_items = [described(i) for i in calendar_items(first, last, classes, portal=True)]
	context.month_items = month_items
	context.month_title = f"{MONTHS[first.month - 1]} {first.year}"
	context.weeks = weeks(first, last, month_items)
	context.weekdays = WEEKDAYS_SHORT
	context.previous_month = (first - timedelta(days=1)).strftime("%Y-%m")
	context.next_month = (last + timedelta(days=1)).strftime("%Y-%m")
	context.upcoming_days = UPCOMING_DAYS

	context.guardian = guardian
	notif = get_notifications(guardian, children)
	context.notifications = notif["items"]
	context.unseen_count = notif["unseen_count"]
	context.no_cache = 1


def month_from(value):
	"""?mwezi=YYYY-MM, else this month (anything else is ignored)."""
	if value and re.fullmatch(r"\d{4}-\d{2}", str(value)):
		year, month = map(int, str(value).split("-"))
		if 2000 <= year <= 2100 and 1 <= month <= 12:
			return date(year, month, 1)
	return getdate(today()).replace(day=1)


def swahili_date(day):
	return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]} {day.year}"


def described(item):
	"""What a parent reads: the title in Swahili for terms and exams, the kind, the date(s)."""
	if item.kind == "Term":
		title = f"Muhula unaanza: {item.term}" if item.what == "opens" else f"Muhula unaisha: {item.term}"
	elif item.kind == "Exam":
		title = f"Mtihani wa {item.exam_name} ({item.class_name})"
	else:
		title = item.title
	when = swahili_date(item.start)
	if item.end != item.start:
		when += f" hadi {swahili_date(item.end)}"
	return frappe._dict(
		title=title,
		kind=item.kind,
		kind_label=KINDS.get(item.kind, "Tukio"),
		when=when,
		start=item.start,
		end=item.end,
		day=item.start.day,
		month_short=MONTHS[item.start.month - 1][:3],
		no_school=not item.is_school_day,
		description=item.get("description"),
	)


def weeks(first, last, items):
	"""The month as weeks (Monday first) of day cells with their events."""
	start = first - timedelta(days=first.weekday())
	end = last + timedelta(days=6 - last.weekday())
	today_date = getdate(today())
	result, week, day = [], [], start
	while day <= end:
		day_items = [i for i in items if i.start <= day <= i.end]
		week.append(
			frappe._dict(
				day=day.day,
				in_month=first <= day <= last,
				is_today=day == today_date,
				kinds=sorted({i.kind for i in day_items}),
				no_school=any(i.no_school for i in day_items),
				weekend=day.weekday() >= 5,
			)
		)
		if len(week) == 7:
			result.append(week)
			week = []
		day += timedelta(days=1)
	return result
