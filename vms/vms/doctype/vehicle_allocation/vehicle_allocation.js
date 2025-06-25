
frappe.ui.form.on("Vehicle Allocation", {
	refresh(frm) {
		if (frm.doc.docstatus == 0) {
			frm.add_custom_button(
				__("Sales Order"),
				function () {
					// eslint-disable-next-line
					let OrderSelector = new vms.OrderSelector(frm);
					OrderSelector.init();
				},
				__("Get Items From")
			);
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__('Generate Delivery Note'), function () {
				frappe.call({
					method: "vms.vms.doctype.vehicle_allocation.vehicle_allocation.generate_delivery_note",
					args: {
						docname: frm.doc.name
					},
					callback: function (r) {
						if (!r.exc) {
							frappe.msgprint(__('Delivery Note(s) generated successfully'));
							frm.reload_doc();
						}
					}
				});
			});
		}
		if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Reallocate Order'), () => {
                let options = (frm.doc.orders || []).map(d => d.sales_order);

                const dialog = new frappe.ui.Dialog({
                    title: 'Reallocate Order',
                    fields: [
                        {
                            fieldname: 'sales_order',
                            label: 'Sales Order',
                            fieldtype: 'Link',
                            options: 'Sales Order',
                            reqd: 1,
                            get_query: () => ({
                                filters: [['name', 'in', options]]
                            })
                        },
                        {
                            fieldname: 'target_allocation',
                            label: 'Target Vehicle Allocation',
                            fieldtype: 'Link',
                            options: 'Vehicle Allocation',
                            reqd: 1,
                            get_query: () => ({
                                filters: [['docstatus', '<', 2]]
                            })
                        }
                    ],
                    primary_action_label: 'Reallocate',
                    primary_action(values) {
                        frappe.call({
                            method: 'vms.vms.doctype.vehicle_allocation.vehicle_allocation.reallocate_order',
                            args: {
                                source_doc: frm.doc.name,
                                sales_order: values.sales_order,
                                target_allocation: values.target_allocation
                            },
                            callback: function (r) {
                                if (!r.exc) {
                                    frappe.msgprint('Order reallocated successfully');
                                    dialog.hide();
                                }
                            }
                        });
                    }
                });

                dialog.show();
            });
        }
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Remove Sales Orders'), () => {
                let dialog = new frappe.ui.Dialog({
                    title: 'Remove Sales Order',
                    fields: [
                        {
                            label: 'Sales Order',
                            fieldname: 'sales_order',
                            fieldtype: 'Link',
                            options: 'Sales Order',
                            reqd: 1,
                            get_query: () => ({
                                filters: [
                                    ['name', 'in', (frm.doc.orders || []).map(row => row.sales_order)]
                                ]
                            })
                        }
                    ],
                    primary_action_label: 'Remove',
                    primary_action(values) {
                        frappe.call({
                            method: 'vms.vms.doctype.vehicle_allocation.vehicle_allocation.remove_sales_order',
                            args: {
                                docname: frm.doc.name,
                                sales_order: values.sales_order
                            },
                            callback: function () {
                                frappe.msgprint(__('Sales Order removed successfully'));
                                dialog.hide();
                                frm.reload_doc();
                            }
                        });
                    }
                });

                dialog.show();
            });
        }
    
		// if (frm.doc.docstatus === 1) {
        //     frm.add_custom_button(__('Generate Sales Invoice'), function() {
        //         frappe.call({
        //             method: "vms.vms.doctype.vehicle_allocation.vehicle_allocation.generate_invoice",
        //             args: {
        //                 docname: frm.doc.name
        //             },
        //             callback: function(r) {
        //                 if (!r.exc) {
        //                     frappe.msgprint(__('Sales Invoice(s) created successfully.'));
        //                     frm.reload_doc();
        //                 }
        //             }
        //         });
        //     });
        // }
	},
});
