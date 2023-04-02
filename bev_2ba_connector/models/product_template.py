from odoo import api, fields, models, _


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ba_ref = fields.Char()

    def update_product_2ba(self):
        """ Update productdata. """
        return {
            "type": "ir.actions.act_window",
            "res_model": "ba.importer.wizard",
            "target": "new",
            "view_mode": "form",
            "context": {
                "skus": self.barcode,
                "update_content": True
            },
        }