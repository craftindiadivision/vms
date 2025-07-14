
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
                let customers = [...new Set((frm.doc.orders || []).map(d => d.customer))];

                const dialog = new frappe.ui.Dialog({
                    title: 'Reallocate Order',
                    fields: [
                        {
                            fieldname: 'customer',
                            label: 'Customer',
                            fieldtype: 'Link',
                            options: 'Customer',
                            reqd: 1,
                            get_query: () => ({
                                filters: [['name', 'in', customers]]
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
                            method: 'vms.vms.doctype.vehicle_allocation.vehicle_allocation.reallocate_customer',
                            args: {
                                source_doc: frm.doc.name,
                                customer: values.customer,
                                target_allocation: values.target_allocation
                            },
                            callback: function (r) {
                                if (!r.exc) {
                                    frappe.msgprint('Reallocated successfully');
                                    dialog.hide();
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                });

                dialog.show();
            });
        }

    if (frm.doc.docstatus === 1) {
        frm.add_custom_button(__('Remove Orders'), () => {
            let customers = [...new Set((frm.doc.orders || []).map(d => d.customer))];

            let dialog = new frappe.ui.Dialog({
                title: 'Remove Orders ',
                fields: [
                    {
                        label: 'Customer',
                        fieldname: 'customer',
                        fieldtype: 'Link',
                        options: 'Customer',
                        reqd: 1,
                        get_query: () => ({
                            filters: [['name', 'in', customers]]
                        })
                    }
                ],
                primary_action_label: 'Remove',
                primary_action(values) {
                    frappe.call({
                        method: 'vms.vms.doctype.vehicle_allocation.vehicle_allocation.remove_customer_orders',
                        args: {
                            docname: frm.doc.name,
                            customer: values.customer
                        },
                        callback: function () {
                            frappe.msgprint(__('Removed successfully'));
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
