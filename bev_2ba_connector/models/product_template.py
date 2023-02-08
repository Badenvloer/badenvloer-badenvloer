from odoo import api, fields, models, _


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ba_ref = fields.Char()