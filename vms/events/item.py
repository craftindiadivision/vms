import frappe
from frappe.utils import flt

def validate(self,method):
    length_cm = flt(self.custom_length)
    width_cm = flt(self.custom_width)
    height_cm = flt(self.custom_height)

    if length_cm and width_cm and height_cm:
        self.custom_volume_per_case = (length_cm * width_cm * height_cm) / 1000000  # m³
    else:
        self.custom_volume_per_case = 0
