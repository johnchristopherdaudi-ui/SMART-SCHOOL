import frappe

# The public admission form is for parents, so everything they see is in Swahili (like the parent portal).
# Stored values stay as they are: Male / Female, and the Class names.
GENDERS = [{"label": "Mvulana", "value": "Male"}, {"label": "Msichana", "value": "Female"}]
LEVELS = {
	1: "Kidato cha Kwanza",
	2: "Kidato cha Pili",
	3: "Kidato cha Tatu",
	4: "Kidato cha Nne",
	5: "Kidato cha Tano",
	6: "Kidato cha Sita",
}
BLANK = {"label": "", "value": ""}


def get_context(context):
	options = {"gender": [BLANK, *GENDERS], "class_applying": [BLANK, *class_options()]}
	for df in context.web_form_doc.get("web_form_fields") or []:
		if df.get("fieldname") in options:
			df["options"] = options[df["fieldname"]]


def class_options():
	"""The school's classes by Form: "Kidato cha Kwanza", with the class name when a Form has several."""
	classes = frappe.get_all("Class", fields=["name", "level"], order_by="level asc, name asc")
	per_level = {}
	for c in classes:
		per_level[c.level] = per_level.get(c.level, 0) + 1
	result = []
	for c in classes:
		label = LEVELS.get(c.level)
		if not label:
			label = c.name
		elif per_level[c.level] > 1:
			label = f"{label} ({c.name})"
		result.append({"label": label, "value": c.name})
	return result
