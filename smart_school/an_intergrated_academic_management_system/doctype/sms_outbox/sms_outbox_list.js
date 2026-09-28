// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.listview_settings["SMS Outbox"] = {
	get_indicator(doc) {
		const colors = { Queued: "orange", Sent: "green", Failed: "red", Test: "blue", Skipped: "gray" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
	onload(listview) {
		if (!(frappe.user.has_role("Headmaster") || frappe.user.has_role("System Manager"))) {
			return;
		}
		listview.page.add_actions_menu_item(__("Try Again"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				return;
			}
			frappe.call({
				method: "smart_school.sms.retry",
				args: { names },
				freeze: true,
				callback: (r) => {
					frappe.show_alert({ message: __("{0} message(s) queued again", [r.message || 0]), indicator: "green" });
					listview.refresh();
				},
			});
		});
	},
};
