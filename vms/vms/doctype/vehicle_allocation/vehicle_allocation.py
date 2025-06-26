# Copyright (c) 2024, Wahni IT Solutions Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from erpnext.accounts.party import get_party_account
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.stock.doctype.item.item import get_item_defaults
from frappe import _
from frappe.contacts.doctype.address.address import get_company_address
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.model.utils import get_fetch_values
from frappe.utils import cint, flt
from pypika import CustomFunction


class VehicleAllocation(Document):
	def validate(self):
		self.check_availability()
		self.calculate_allocated_qty()

	def on_submit(self):
		if not self.orders:
			frappe.throw(_("Cannot submit without any items."))
		self.update_allocated_qty()
		# self.generate_invoice()
		# self.generate_delivery_note()

	def on_cancel(self):
		self.update_allocated_qty()
		self.unlink_delivery_notes()
  
	def on_update_after_submit(self):
		self.calculate_allocated_qty()
		self.update_allocated_qty()
		

	def update_allocated_qty(self):
		if self.docstatus == 1:
			for row in self.orders:
				allocated_qty = row.order_qty - row.pending_qty
				allocated_qty += row.allocated_qty
				frappe.db.set_value(
					"Sales Order Item", row.sales_order_detail, "allocated_qty", allocated_qty
				)
		elif self.docstatus == 2:
			for row in self.orders:
				allocated_qty = frappe.db.get_value(
					"Sales Order Item", row.sales_order_detail, "allocated_qty"
				)
				allocated_qty -= row.allocated_qty
				frappe.db.set_value(
					"Sales Order Item", row.sales_order_detail, "allocated_qty", allocated_qty
				)
    
	def unlink_delivery_notes(self):
		linked_dns = frappe.get_all(
			"Delivery Note",
			filters={
				"custom_vehicle_allocation": self.name,
				"docstatus": ["<", 2]
			},
			pluck="name"
		)

		for dn in linked_dns:
			dn_doc = frappe.get_doc("Delivery Note", dn)
			dn_doc.custom_vehicle_allocation = None
			dn_doc.save(ignore_permissions=True)

		frappe.msgprint(_("Unlinked Delivery Notes from Vehicle Allocation."))

	@frappe.whitelist()
	def generate_invoice(self):
		sales_order_map = {}
		row_qty_map = {}

		for row in self.orders:
			sales_order_map.setdefault(row.sales_order, []).append(row.sales_order_detail)
			row_qty_map[row.sales_order_detail] = row.allocated_qty

		for order, rows in sales_order_map.items():
			# ✅ Check if invoice already exists
			exists = frappe.db.exists("Sales Invoice", {
				"vehicle_allocation": self.name,
				"custom_against_sales_order": order,
				"docstatus": ["<", 2]
			})

			if exists:
				frappe.throw(f"Sales Invoice already exists for Sales Order {order} in this Vehicle Allocation.")

			doc = self.make_sales_invoice(order, rows, row_qty_map)
			if doc and doc.items:
				doc.save()


				for row in self.orders:
					if row.sales_order == order and row.sales_order_detail in rows:
						row.sales_invoice_reference = doc.name

				self.save(ignore_permissions=True)

		frappe.publish_realtime("invoice_generation")


	def make_sales_invoice(self, order, rows, row_qty_map):
		# reason why this is put here is to let people extend this method to override
		def postprocess(source, target):
			set_missing_values(source, target)
			# Get the advance paid Journal Entries in Sales Invoice Advance
			if target.get("allocate_advances_automatically"):
				target.set_advances()

		def set_missing_values(source, target):
			target.flags.ignore_permissions = True
			target.run_method("set_missing_values")
			target.run_method("set_po_nos")
			target.run_method("calculate_taxes_and_totals")
			target.run_method("set_use_serial_batch_fields")
			target.custom_against_sales_order = order
			target.update_stock = 1

			if source.company_address:
				target.update({"company_address": source.company_address})
			else:
				# set company address
				target.update(get_company_address(target.company))

			if target.company_address:
				target.update(get_fetch_values("Sales Invoice", "company_address", target.company_address))

			# set the redeem loyalty points if provided via shopping cart
			if source.loyalty_points and source.order_type == "Shopping Cart":
				target.redeem_loyalty_points = 1

			target.debit_to = get_party_account("Customer", source.customer, source.company)
			target.vehicle_allocation = self.name

		def update_item(source, target, source_parent):
			allocated_qty = row_qty_map.get(source.name)
			
			if not allocated_qty:
				return

			target.qty = allocated_qty
			target.amount = flt(allocated_qty) * flt(source.rate)
			target.base_amount = target.amount * flt(source_parent.conversion_rate)

			if source_parent.project:
				target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center")

			if target.item_code:
				item = get_item_defaults(target.item_code, source_parent.company)
				item_group = get_item_group_defaults(target.item_code, source_parent.company)
				cost_center = item.get("selling_cost_center") or item_group.get("selling_cost_center")

				if cost_center:
					target.cost_center = cost_center


		doclist = get_mapped_doc(
			"Sales Order",
			order,
			{
				"Sales Order": {
					"doctype": "Sales Invoice",
					"field_map": {
						"party_account_currency": "party_account_currency",
						"payment_terms_template": "payment_terms_template",
					},
					"field_no_map": ["payment_terms_template"],
					"validation": {"docstatus": ["=", 1]},
				},
				"Sales Order Item": {
					"doctype": "Sales Invoice Item",
					"field_map": {
						"name": "so_detail",
						"parent": "sales_order",
					},
					"postprocess": update_item,
					"condition": (
						lambda doc: (
							doc.qty
							and (doc.base_amount == 0 or abs(doc.billed_amt) < abs(doc.amount))
							and doc.name in rows
						)
					),
				},
				"Sales Taxes and Charges": {"doctype": "Sales Taxes and Charges", "add_if_empty": True},
				"Sales Team": {"doctype": "Sales Team", "add_if_empty": True},
			},
			None,
			postprocess,
			ignore_permissions=False,
		)

		automatically_fetch_payment_terms = cint(
			frappe.db.get_single_value("Accounts Settings", "automatically_fetch_payment_terms")
		)
		if automatically_fetch_payment_terms:
			doclist.set_payment_schedule()

		return doclist

	def calculate_allocated_qty(self):
		self.allocated_qty = 0
		self.allocated_weight = 0
		self.allocated_volume = 0

		for order in self.orders:

			weight_per_unit, volume_per_case, conversion_factor, ordered_qty = frappe.db.get_value(
				"Sales Order Item",
				order.sales_order_detail,
				["weight_per_unit", "custom_volume_per_case", "conversion_factor", "qty"]
			)

	
			if flt(order.allocated_qty) > flt(ordered_qty):
				frappe.throw(
					_(f"Allocated quantity ({order.allocated_qty}) cannot exceed ordered quantity ({ordered_qty}) "
					f"for item {order.item or order.sales_order_detail}.")
				)


			order.allocated_weight = flt(order.allocated_qty) * flt(weight_per_unit * conversion_factor)
			order.allocated_volume = flt(order.allocated_qty) * flt(volume_per_case)

			# Sum totals
			self.allocated_qty += order.allocated_qty
			self.allocated_weight += order.allocated_weight
			self.allocated_volume += order.allocated_volume or 0


		if self.allocated_qty > self.qty_capacity:
			frappe.msgprint(_("Allocated quantity is more than vehicle capacity."))

		if self.allocated_weight > self.weight_capacity:	
			frappe.msgprint(_("Allocated weight is more than vehicle capacity."))
   
		if self.allocated_volume > self.volume_capacity: 
				frappe.msgprint(_("Allocated volume is more than vehicle capacity."))
   

	def check_availability(self):
		duplicate = frappe.db.get_all(
			self.doctype,
			filters={
				"docstatus": ["!=", 2],
				"delivery_date": self.delivery_date,
				"name": ["!=", self.name],
			},
			or_filters={"vehicle": self.vehicle, "driver": self.driver},
		)
		if duplicate:
			frappe.throw(_("Vehicle or driver already allocated for the given delivery date."))

	@frappe.whitelist()
	def get_order_items(self):
		routes = [d.route for d in self.routes]
		territories = [d.territory for d in self.territories]

		draft_allocations = (
			frappe.db.get_all("Vehicle Allocation", filters={"docstatus": 0}, pluck="name") or []
		)
		draft_allocations.append(self.name)
		exclude = []
		if draft_allocations:
			exclude = frappe.db.get_all(
				"Vehicle Allocation Order",
				filters={"parent": ["in", draft_allocations]},
				pluck="sales_order_detail",
			)

		so = frappe.qb.DocType("Sales Order")
		soi = frappe.qb.DocType("Sales Order Item")

		DateFormat = CustomFunction("DATE_FORMAT", ["date", "format"])
		orders = []
		company_list = frappe.db.get_all("Company", pluck="name", order_by="name desc")
		for company in company_list:
			result = (
				frappe.qb.from_(so)
				.inner_join(soi)
				.on(soi.parent == so.name)
				.select(
					so.name.as_("sales_order"),
					so.customer,
					DateFormat(so.transaction_date, "%d-%m-%Y").as_("date"),
					so.company,
					so.transaction_date,
					so.route,
					soi.custom_volume_per_case,
					soi.name.as_("sales_order_detail"),
					soi.item_code.as_("item"),
					(soi.qty - soi.allocated_qty).as_("qty"),
					soi.qty.as_("order_qty"),
					soi.rate,
					soi.uom,
					soi.stock_qty,
					(soi.weight_per_unit * (soi.stock_qty)).as_("weight"),
     				(soi.custom_volume_per_case * (soi.qty)).as_("volume"),

				)
				.where(so.docstatus == 1)
				.where(so.company == company)
				.where(so.status != "Closed")
				.where(soi.allocated_qty < soi.qty)
				.where(soi.delivered_qty < soi.qty)
				.where((soi.billed_amt) < (soi.amount))
        		.where(so.delivery_date == self.delivery_date)
				.orderby(so.transaction_date)
			)
			if exclude:
				result = result.where(soi.name.notin(exclude))
			if territories:
				result = result.where(so.territory.isin(territories))
			if routes:
				result = result.where(so.route.isin(routes))

			orders += result.run(as_dict=True) or []

		order_dict = {}
		order_details = {}
		for order in orders:
			order_dict.setdefault(
				order.get("sales_order"),
				{
					"sales_order": order.get("sales_order"),
					"customer": order.get("customer"),
					"date": order.get("date"),
					"company": order.get("company"),
					"transaction_date": order.get("transaction_date"),
					"route": order.get("route", ""), 
				},
			)
			order_details.setdefault(order.get("sales_order"), [])
			order_details[order.get("sales_order")].append(
				{
					"sales_order_detail": order.get("sales_order_detail"),
					"item": order.get("item"),
					"qty": order.get("qty"),
					"rate": order.get("rate"),
					"uom": order.get("uom"),
					"stock_qty": order.get("stock_qty"),
					"weight": order.get("weight"),
					"volume":order.get("volume"),
					"sales_order": order.get("sales_order"),
					"customer": order.get("customer"),
					"date": order.get("date"),
					"company": order.get("company"),
					"transaction_date": order.get("transaction_date"),
					"route": order.get("route", ""),
					"order_qty": order.get("order_qty"),
				}
			)


		return {"orders": list(order_dict.values()), "items": order_details}


	@frappe.whitelist()
	def generate_delivery_note(self):
		sales_order_map = {}
		row_qty_map = {}

		for row in self.orders:
			if not row.delivery_note_reference:
				sales_order_map.setdefault(row.sales_order, []).append(row.sales_order_detail)
				row_qty_map[row.sales_order_detail] = row.allocated_qty

		if not sales_order_map:
			frappe.throw("All rows already have Delivery Notes.")

		for sales_order, order_details in sales_order_map.items():
			existing_dn = frappe.get_all(
				"Delivery Note",
				filters={
					"docstatus": ("<", 2),
					"custom_against_sales_order": sales_order
				},
				fields=["name"],
				limit=1
			)

			if existing_dn:
				dn = frappe.get_doc("Delivery Note", existing_dn[0].name)
				dn.custom_vehicle_allocation = self.name
				dn.save(ignore_permissions=True)

				for row in self.orders:
					if row.sales_order == sales_order and row.sales_order_detail in order_details:
						row.delivery_note_reference = dn.name

			else:
				dn = self.make_delivery_note(sales_order, order_details, row_qty_map)

				if dn and dn.items:
					dn.custom_vehicle_allocation = self.name
					dn.save(ignore_permissions=True)

					for row in self.orders:
						if row.sales_order == sales_order and row.sales_order_detail in order_details:
							row.delivery_note_reference = dn.name
       
		self.save(ignore_permissions=True)
		frappe.publish_realtime("delivery_note_generation")



	def make_delivery_note(self, order, rows, row_qty_map):
		def postprocess(source, target):
			target.flags.ignore_permissions = True
			target.custom_vehicle_allocation = self.name
			target.custom_against_sales_order = order
			target.driver = self.driver
			target.vehicle_no = self.vehicle

			# Set company address
			if source.company_address:
				target.company_address = source.company_address
			else:
				target.update(get_company_address(target.company))

			if target.company_address:
				target.update(get_fetch_values("Delivery Note", "company_address", target.company_address))

		def update_item(source, target, source_parent):
			target.qty = row_qty_map.get(source.name) or source.qty
			target.against_sales_order = source_parent.name
			target.so_detail = source.name

		return get_mapped_doc(
			"Sales Order",
			order,
			{
				"Sales Order": {
					"doctype": "Delivery Note",
					"validation": {"docstatus": ["=", 1]},
				},
				"Sales Order Item": {
					"doctype": "Delivery Note Item",
					"field_map": {
						"name": "so_detail",
						"parent": "against_sales_order"
					},
					"postprocess": update_item,
					"condition": (
						lambda doc: (
							doc.qty
							and doc.delivered_qty < doc.qty
							and doc.name in rows
						)
					)
				}
			},
			None,
			postprocess,
			ignore_permissions=False
		)

@frappe.whitelist()
def generate_delivery_note(docname):
    doc = frappe.get_doc("Vehicle Allocation", docname)
    doc.generate_delivery_note()


@frappe.whitelist()
def generate_invoice(docname):
    doc = frappe.get_doc("Vehicle Allocation", docname)
    doc.generate_invoice()
    
    
@frappe.whitelist()
def reallocate_order(source_doc, sales_order, target_allocation):
    if source_doc == target_allocation:
        frappe.throw("Source and Target Vehicle Allocation cannot be the same.")

    source = frappe.get_doc("Vehicle Allocation", source_doc)
    target = frappe.get_doc("Vehicle Allocation", target_allocation)

    rows_to_move = [row for row in source.orders if row.sales_order == sales_order]

    if not rows_to_move:
        frappe.throw("No matching rows found for the selected Sales Order.")

    existing_so_details = {row.sales_order_detail for row in target.orders}
    duplicates = [row.sales_order_detail for row in rows_to_move if row.sales_order_detail in existing_so_details]

    if duplicates:
        frappe.throw(f"The selected Sales Orders are already allocated in {target_allocation}")

    for row in rows_to_move:
        target.append("orders", {
            "sales_order": row.sales_order,
            "sales_order_detail": row.sales_order_detail,
            "company": row.company,
            "delivery_note_reference": row.delivery_note_reference,
            "sales_invoice_reference": row.sales_invoice_reference,
            "customer": row.customer,
            "route": row.route,
            "item": row.item,
            "unit_weight": row.unit_weight,
            "order_qty": row.order_qty,
            "pending_qty": row.pending_qty,
            "allocated_volume": row.allocated_volume,
            "allocated_qty": row.allocated_qty,
            "allocated_weight": row.allocated_weight,
        })

        delivery_notes = frappe.get_all(
            "Delivery Note",
            filters={
                "custom_against_sales_order": row.sales_order,
                "custom_vehicle_allocation": source_doc,
                "docstatus": ["<", 2]
            },
            pluck="name"
        )

        for dn in delivery_notes:
            dn_doc = frappe.get_doc("Delivery Note", dn)
            dn_doc.custom_vehicle_allocation = target_allocation
            dn_doc.save(ignore_permissions=True)

        source.remove(row)

    # Recalculate allocation values for both docs
    source.calculate_allocated_qty()
    target.calculate_allocated_qty()
    source.update_allocated_qty()
    target.update_allocated_qty()

    source.save(ignore_version=True)
    target.save(ignore_version=True)
    frappe.db.commit()


    frappe.msgprint(f"Sales Order {sales_order} moved to Vehicle Allocation {target_allocation}")
    
    
@frappe.whitelist()
def remove_sales_order(docname, sales_order):
    doc = frappe.get_doc("Vehicle Allocation", docname)
    rows_to_remove = [row for row in doc.orders if row.sales_order == sales_order]

    if not rows_to_remove:
        frappe.throw(f"No rows found for Sales Order {sales_order} in Vehicle Allocation {docname}.")

    for row in rows_to_remove:
        if row.sales_order_detail:
            current_allocated = frappe.db.get_value("Sales Order Item", row.sales_order_detail, "allocated_qty") or 0
            updated_allocated = flt(current_allocated) - flt(row.allocated_qty)
            frappe.db.set_value("Sales Order Item", row.sales_order_detail, "allocated_qty", updated_allocated)

        doc.remove(row)

    dn_list = frappe.get_all(
        "Delivery Note",
        filters={
            "custom_vehicle_allocation": docname,
            "custom_against_sales_order": sales_order,
            "docstatus": ["<", 2] 
        },
        pluck="name"
    )

    for dn in dn_list:
        dn_doc = frappe.get_doc("Delivery Note", dn)
        dn_doc.custom_vehicle_allocation = None
        dn_doc.save(ignore_permissions=True)

    # Recalculate allocation values after removal
    doc.calculate_allocated_qty()
    doc.update_allocated_qty()

    doc.save(ignore_permissions=True)
    frappe.db.commit()


    frappe.msgprint(f"Sales Order {sales_order} removed from Vehicle Allocation {docname} and unlinked from delivery note")




