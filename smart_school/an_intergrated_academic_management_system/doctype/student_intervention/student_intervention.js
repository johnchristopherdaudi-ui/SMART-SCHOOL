// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("Student Intervention", {
	setup(frm) {
		frm.set_query("responsible", () => ({ query: "smart_school.interventions.staff_user_query" }));
	},
});
