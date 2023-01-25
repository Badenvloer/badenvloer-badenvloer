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
            skus = wizard.skus.split("/n")

            # loop over all GTIN's to find duplicate products.
            for sku in skus:
                prod = self.env['product.template'].search([
                    ("barcode", "=", sku)
                ])

                if prod:
                    raise UserError('Product with GTIN ' + sku + ' already exists')

            # Execute call
            for sku in skus:
                if datetime.now() > datetime.fromtimestamp(
                        float(self.env.ref('ba_importer.ba_importer_authorization_expire').value)):
                    self.refresh_access()

                product = self.get_product_by_gtin(sku)
                if 'IsError' in product.keys():
                    continue

                thumbnail = self.get_product_thumbnail(product.get('ManufacturerGLN'), product.get('Productcode'))

                _logger.warning(product)

                # add new product
                self.env["product.template"].create({
                    "name": product.get("Brand", "Merkloos") + " " + product.get('Model') + " " + product.get(
                        'Version'),
                    "description": product.get("Description"),
                    "description_sale": product.get("LongDescription"),
                    "weight": product.get("WeightQuantity"),
                    "weight_uom_name": product.get("WeightMeasureUnitDescription"),
                    "barcode": product.get("GTIN"),
                    "image_1920": thumbnail
                })

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
                "username": self.env.ref('ba_importer.ba_importer_username').value,
                "password": self.env.ref('ba_importer.ba_importer_password').value,
                "client_id": self.env.ref('ba_importer.ba_importer_client_id').value,
                "client_secret": self.env.ref('ba_importer.ba_importer_client_secret').value,
            }
        )
        res = r.json()

        if res['error']:
            raise AccessError(res['error'])

        self.env.ref('ba_importer.ba_importer_authorization_code').value = res['access_token']
        self.env.ref('ba_importer.ba_importer_refresh_token').value = res['refresh_token']
        expire = datetime.timestamp(datetime.now() + timedelta(seconds=res['expires_in'] - 100))
        self.env.ref('ba_importer.ba_importer_authorization_expire').value = expire

    def refresh_access(self):
        """
        Gets the authorization from the 2ba auth server using the refresh token.
        has a fallback to the password method. when the refresh token is invalid.
        """
        r = requests.post(
            url=self.authUrl,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.env.ref('ba_importer.ba_importer_refresh_token').value,
                "client_id": self.env.ref('ba_importer.ba_importer_client_id').value,
                "client_secret": self.env.ref('ba_importer.ba_importer_client_secret').value,
            }
        )
        res = r.json()

        if res['error']:
            if res['error'] == 'invalid_grant':
                return self.request_access()

            raise AccessError(res['error'])

        self.env.ref('ba_importer.ba_importer_authorization_code').value = res['access_token']
        self.env.ref('ba_importer.ba_importer_refresh_token').value = res['refresh_token']
        expire = datetime.timestamp(datetime.now() + timedelta(seconds=res['expires_in'] - 100))
        self.env.ref('ba_importer.ba_importer_authorization_expire').value = expire

    def get_product_by_gtin(self, gtin):
        """
        Retrives the product from 2ba api and returns a json formatted product
        """
        r = requests.get(url=self.baseUrl + "/json/Product/DetailsForProduct", params={
            "gtin": gtin
        },
                         headers={
                             "Authorization": "Bearer " + self.env.ref(
                                 'ba_importer.ba_importer_authorization_code').value
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
                             "Authorization": "Bearer " + self.env.ref(
                                 'ba_importer.ba_importer_authorization_code').value
                         })

        return b64encode(r.content).decode("utf-8")