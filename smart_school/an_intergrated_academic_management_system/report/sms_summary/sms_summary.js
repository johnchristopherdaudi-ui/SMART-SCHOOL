// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.query_reports["SMS Summary"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -11),
		},
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{
			fieldname: "message_type",
			label: __("Type"),
			fieldtype: "Select",
			options: "\nResults Published\nPayment Received\nFee Reminder\nFee Overdue\nAnnouncement\nEvent Reminder\nLeave Decision",
		},
	],
};
