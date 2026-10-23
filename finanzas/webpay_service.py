from transbank.common.integration_api_keys import IntegrationApiKeys
from transbank.common.integration_commerce_codes import IntegrationCommerceCodes
from transbank.common.integration_type import IntegrationType
from transbank.common.options import WebpayOptions
from transbank.webpay.webpay_plus.transaction import Transaction


# URL del formulario Webpay Plus para el ambiente de integración.
URL_WEBPAY_INTEGRACION = (
    "https://webpay3gint.transbank.cl/webpayserver/initTransaction"
)


def obtener_transaccion_webpay():
    """
    Crea el cliente de Webpay Plus para pruebas de integración.
    Estas credenciales no permiten cobrar dinero real.
    """
    opciones = WebpayOptions(
        IntegrationCommerceCodes.WEBPAY_PLUS,
        IntegrationApiKeys.WEBPAY,
        IntegrationType.TEST,
    )

    return Transaction(opciones)