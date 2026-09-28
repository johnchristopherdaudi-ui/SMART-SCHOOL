// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.query_reports["Model Performance"] = {
	filters: [
		{
			fieldname: "risk_model",
			label: __("Risk Model"),
			fieldtype: "Link",
			options: "Risk Model",
			description: __("Empty: the model in use"),
		},
	],
};
