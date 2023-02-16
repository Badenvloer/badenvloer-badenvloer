from odoo import models, fields
from odoo.exceptions import AccessError, UserError
import logging
import requests
from datetime import datetime, timedelta
from base64 import b64encode

_logger = logging.getLogger(__name__)


class BaImporterWizard(models.TransientModel):
    """
    Wizard for importing products from the 2ba api
    """
    _name = 'ba.importer.wizard'
    _description = '2ba importer wizard'

    baseUrl = "https://api.2ba.nl/1"
    authUrl = "https://authorize.2ba.nl/OAuth/Token"
    skus = fields.Text()

    def execute_import(self):
        """
        Imports products according to a list of products GTIN
        First we check if the product doesn't exist already. if so we give an error.
        When no duplicate products are found we start importing the products
        """

        for wizard in self:
            skus = wizard.skus.splitlines()

            # loop over all GTIN's to find duplicate products.
            for sku in skus:
                prod = self.env['product.template'].sudo().search([
                    ("barcode", "=", sku)
                ])

                if prod:
                    raise UserError('Product with GTIN ' + sku + ' already exists')

            # Execute call
            for sku in skus:
                if datetime.now() > datetime.fromtimestamp(
                        float(self.env.sudo().ref('bev_2ba_connector.ba_importer_authorization_expire').value)):
                    self.refresh_access()

                product = self.get_product_by_gtin(sku)
                if 'IsError' in product.keys():
                    raise UserError("[%s]: %s" % (sku, product.get("ErrorMessage")))
                    continue

                thumbnail = self.get_product_thumbnail(product.get('ManufacturerGLN'), product.get('Productcode'))

                _logger.info(product)
                attributes = self._get_product_attributes(sku)
                attr_list = []
                # loop features
                for attr in attributes.get("Features"):
                    res = self.env['product.attribute'].sudo().search([
                        ("ba_ref", "=", attr.get("FeatureID"))
                    ], limit=1)
                    if not res:
                        res = self.env['product.attribute'].sudo().search([
                            ("name", "=", attr.get("Description"))
                        ], limit=1)
                        if not res:
                            res = self.env["product.attribute"].sudo().create({
                                "name": attr.get("Description"),
                                "ba_ref": attr.get("FeatureID")
                            })

                    # Create attribute res
                    val = ""
                    if attr.get("LogicalValue") != None:
                        val = "Ja" if attr.get("LogicalValue") else "Nee"
                    if attr.get("NumericValue") != None:
                        val = str(attr.get("NumericValue"))
                    if attr.get("RangeLowerValue") != None:
                        val = str(attr.get("RangeLowerValue")) + " - " + str(attr.get("RangeUpperValue"))
                    if attr.get("ValueDescription") != None:
                        val = str(attr.get("ValueDescription"))

                    value = self.env['product.attribute.value'].sudo().search([
                        ("attribute_id", "=", res.id),
                        ("name", "=", val)
                    ])
                    if not value:
                        value = self.env["product.attribute.value"].sudo().create({
                            "attribute_id": res.id,
                            "name": val,
                        })
                    attr_list.append(
                        (0, 0, {
                            'attribute_id': res.id,
                            'value_ids': [(6, 0, [value.id])]
                        })
                    )
                name = product.get("Description")
                if product.get('Model' ,""):
                    name += " " + product.get('Model' ,"")
                if product.get('Version', ""):
                    name += " " + product.get('Version', "")
                supplier_price = self.get_supplier_price(product.get('ManufacturerGLN'), "Korver")
                template = {
                    "name": product.get("Description"),
                    "description": product.get("Description"),
                    "description_sale": product.get("LongDescription"),
                    "weight": product.get("WeightQuantity"),
                    "weight_uom_name": product.get("WeightMeasureUnitDescription"),
                    "barcode": product.get("GTIN"),
                    "detailed_type": "product",
                    "ba_ref": product.get("id"),
                    'attribute_line_ids': attr_list,
                    "default_code": product.get("Productcode"),
                    "standard_price": supplier_price if supplier_price else 0
                }
                if thumbnail:
                    template['image_1920'] = thumbnail
                # add new product
                prod = self.env["product.template"].sudo().create(template)

    @staticmethod
    def test_api(endpoint):
        """
        Does a get request to an endpoint of choice and returns the json response
        """
        r = requests.get(url=endpoint)
        data = r.json()
        return data

    def request_access(self):
        """
        Gets the authorization from the 2ba auth server using the supplied username and password.
        """
        r = requests.post(
            url=self.authUrl,
            data={
                "grant_type": "password",
                "username": self.env.sudo().ref('bev_2ba_connector.ba_importer_username').value,
                "password": self.env.sudo().ref('bev_2ba_connector.ba_importer_password').value,
                "client_id": self.env.sudo().ref('bev_2ba_connector.ba_importer_client_id').value,
                "client_secret": self.env.sudo().ref('bev_2ba_connector.ba_importer_client_secret').value,
            }
        )
        res = r.json()

        if res.get("error"):
            raise AccessError(res.get("error"))

        self.env.sudo().ref('bev_2ba_connector.ba_importer_authorization_code').value = res['access_token']
        self.env.sudo().ref('bev_2ba_connector.ba_importer_refresh_token').value = res['refresh_token']
        expire = datetime.timestamp(datetime.now() + timedelta(seconds=res['expires_in'] - 100))
        self.env.sudo().ref('bev_2ba_connector.ba_importer_authorization_expire').value = expire

    def refresh_access(self):
        """
        Gets the authorization from the 2ba auth server using the refresh token.
        has a fallback to the password method. when the refresh token is invalid.
        """
        r = requests.post(
            url=self.authUrl,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.env.sudo().ref('bev_2ba_connector.ba_importer_refresh_token').value,
                "client_id": self.env.sudo().ref('bev_2ba_connector.ba_importer_client_id').value,
                "client_secret": self.env.sudo().ref('bev_2ba_connector.ba_importer_client_secret').value,
            }
        )
        res = r.json()

        if res.get("error"):
            if res.get("error") == 'invalid_grant':
                return self.request_access()

            raise AccessError(res.get("error"))

        self.env.sudo().ref('bev_2ba_connector.ba_importer_authorization_code').value = res.get("access_token")
        self.env.sudo().ref('bev_2ba_connector.ba_importer_refresh_token').value = res.get("refresh_token")
        expire = datetime.timestamp(datetime.now() + timedelta(seconds=res.get("expires_in") - 100))
        self.env.sudo().ref('bev_2ba_connector.ba_importer_authorization_expire').value = expire

    def get_product_by_gtin(self, gtin):
        """
        Retrives the product from 2ba api and returns a json formatted product
        """
        r = requests.get(url=self.baseUrl + "/json/Product/DetailsForProduct", params={
            "gtin": gtin
        },
                         headers={
                             "Authorization": "Bearer " + self.env.sudo().ref(
                                 'bev_2ba_connector.ba_importer_authorization_code').value
                         })

        return r.json()

    def get_product_thumbnail(self, gln, productcode):
        """
        Retrives the product thumbnail from 2ba api and returns a base64 encoded image

        """

        r = requests.get(url=self.baseUrl + "/json/Thumbnail/product", params={
            "gln": gln,
            "productcode": productcode
        },
                         headers={
                             "Authorization": "Bearer " + self.env.sudo().ref(
                                 'bev_2ba_connector.ba_importer_authorization_code').value
                         })
        if r.status_code != 200:
            return False
        return b64encode(r.content).decode("utf-8")

    def get_supplier_price(self, gln, supplier):
        """
        Retrives the product thumbnail from 2ba api and returns a base64 encoded image

        """

        r = requests.get(url=self.baseUrl + "/json/TradeItem/ForGLN", params={
            "gln": gln,
        },
                         headers={
                             "Authorization": "Bearer " + self.env.sudo().ref(
                                 'bev_2ba_connector.ba_importer_authorization_code').value
                         })

        result = r.json()
        supplier_price = False
        for item in result.get("TradeItems"):
            if item.get("SupplierName") == "Korver Holland":
                supplier_price = item.get("GrossPriceInPriceUnit")

        if supplier_price:
            return supplier_price
        return False


    def _get_product_attributes(self, gtin):
        r = requests.get(url=self.baseUrl + "/json/Product/DetailsByGtinA", params={
            "gtin": gtin,
            "includeFeatures": "true"
        },
                         headers={
                             "Authorization": "Bearer " + self.env.sudo().ref(
                                 'bev_2ba_connector.ba_importer_authorization_code').value
                         })

        return r.json()
