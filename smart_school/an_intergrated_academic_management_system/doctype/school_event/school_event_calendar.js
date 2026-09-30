// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

// The month calendar shows the school's events and, from their own dates, term openings and closings and exams
frappe.views.calendar["School Event"] = {
	field_map: {
		start: "start_date",
		end: "end_date",
		id: "name",
		title: "title",
		allDay: "all_day",
		color: "color",
		convertToUserTz: "convert_to_user_tz",
	},
	get_events_method: "smart_school.school_calendar.get_calendar_events",
	options: { header: { left: "prev,next today", center: "title", right: "month" } },
	// Terms, exams and yearly holidays are moved on their own forms, not by dragging them here
	prepare_events(events) {
		const prepared = frappe.views.Calendar.prototype.prepare_events.call(this, events);
		prepared.forEach((e) => {
			if (e.derived) e.editable = false;
		});
		return prepared;
	},
};
