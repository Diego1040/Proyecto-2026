from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import (
    Apoderado,
    ApoderadoJugador,
    Jugador,
    Usuario,
)

from .models import Beca, Cuota, Pago
from .services import obtener_resumen_morosidad


class HU11WebpayTests(TestCase):

    def setUp(self):
        self.usuario = Usuario.objects.create_user(
            rut="12345678-5",
            password="PruebaSegura-2026",
        )

        self.apoderado = Apoderado.objects.create(
            usuario=self.usuario,
            rut="12345678-5",
            nombres="Isidora",
            apellidos="Prueba",
            telefono="+56911111111",
            email="isidora@example.com",
        )

        self.jugador = Jugador.objects.create(
            rut="11111111-1",
            nombres="Tomas",
            apellidos="Vergara",
            fecha_nacimiento=date(2012, 5, 10),
            rama=Jugador.Rama.VARONES,
            estado=Jugador.Estado.ACTIVO,
            procedencia=Jugador.Procedencia.INDEPENDIENTE,
        )

        ApoderadoJugador.objects.create(
            apoderado=self.apoderado,
            jugador=self.jugador,
            parentesco="Madre",
            activo=True,
            puede_gestionar=True,
            es_principal=True,
        )

        self.cuota = Cuota.objects.create(
            jugador=self.jugador,
            concepto="Cuota de prueba",
            periodo=date(2026, 10, 1),
            monto=Decimal("15000"),
            fecha_vencimiento=date(2026, 10, 31),
            estado=Cuota.Estado.PENDIENTE,
        )

        self.client.force_login(self.usuario)

    def crear_pago(self, estado=Pago.Estado.INICIADO):
        return Pago.objects.create(
            cuota=self.cuota,
            usuario=self.usuario,
            monto=self.cuota.monto,
            token_ws="token-prueba",
            estado=estado,
        )

    def respuesta_webpay(
        self,
        pago,
        estado="AUTHORIZED",
        codigo=0,
    ):
        return {
            "status": estado,
            "response_code": codigo,
            "amount": int(pago.monto),
            "buy_order": pago.orden_compra,
            "session_id": pago.session_id,
            "transaction_date": "2026-10-11T22:11:52.245Z",
            "authorization_code": "123456",
        }

    def test_detalle_por_cuota_en_tesoreria_respeta_los_accesos(self):
        pago = self.crear_pago(Pago.Estado.CONFIRMADO)
        pago.codigo_autorizacion = "AUT-PRUEBA"
        pago.save(update_fields=["codigo_autorizacion"])
        panel = reverse("finanzas:tesoreria")
        recibo = reverse("finanzas:comprobante_pago", args=[pago.pk])
        self.assertContains(self.client.get(recibo), pago.codigo_autorizacion)
        self.assertEqual(self.client.get(panel).status_code, 403)

        tesorero = Usuario.objects.create_user(rut="22222222-2")
        tesorero.groups.add(Group.objects.create(name="Tesorería"))
        self.client.force_login(tesorero)
        respuesta = self.client.get(panel)
        self.assertContains(respuesta, pago.orden_compra)
        self.assertContains(respuesta, pago.codigo_autorizacion)
        self.assertNotContains(respuesta, pago.token_ws)
        self.assertEqual(self.client.get(recibo).status_code, 404)

    # PRUEBA 1: el importe enviado por el navegador no modifica la cuota.

    @patch("finanzas.views.obtener_transaccion_webpay")
    def test_iniciar_pago_crea_intento_y_usa_monto_de_cuota(
        self, obtener_transaccion
    ):
        obtener_transaccion.return_value.create.return_value = {
            "token": "token-nuevo",
            "url": (
                "https://webpay3gint.transbank.cl/"
                "webpayserver/init_transaction.cgi"
            ),
        }

        response = self.client.post(
            reverse(
                "finanzas:iniciar_pago",
                args=[self.cuota.pk],
            ),
            {"monto": "1"},
        )

        self.assertEqual(response.status_code, 200)

        pago = Pago.objects.get(cuota=self.cuota)

        self.assertEqual(pago.monto, Decimal("15000"))
        self.assertEqual(pago.token_ws, "token-nuevo")
        self.assertEqual(pago.estado, Pago.Estado.INICIADO)

        obtener_transaccion.return_value.create.assert_called_once()

    # PRUEBA 2: un pago autorizado confirma el pago y la cuota.

    @patch("finanzas.views.obtener_transaccion_webpay")
    def test_retorno_autorizado_confirma_pago_y_cuota(
        self, obtener_transaccion
    ):
        pago = self.crear_pago()

        obtener_transaccion.return_value.commit.return_value = (
            self.respuesta_webpay(pago)
        )

        response = self.client.post(
            reverse("finanzas:retorno_webpay"),
            {"token_ws": pago.token_ws},
        )

        pago.refresh_from_db()
        self.cuota.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pago.estado, Pago.Estado.CONFIRMADO)
        self.assertEqual(self.cuota.estado, Cuota.Estado.PAGADA)
        self.assertEqual(pago.codigo_respuesta, 0)

    # PRUEBA 3: un pago rechazado deja la cuota pendiente.

    @patch("finanzas.views.obtener_transaccion_webpay")
    def test_retorno_rechazado_deja_cuota_pendiente(
        self, obtener_transaccion
    ):
        pago = self.crear_pago()

        obtener_transaccion.return_value.commit.return_value = (
            self.respuesta_webpay(
                pago,
                estado="FAILED",
                codigo=-1,
            )
        )

        self.client.post(
            reverse("finanzas:retorno_webpay"),
            {"token_ws": pago.token_ws},
        )

        pago.refresh_from_db()
        self.cuota.refresh_from_db()

        self.assertEqual(pago.estado, Pago.Estado.RECHAZADO)
        self.assertEqual(self.cuota.estado, Cuota.Estado.PENDIENTE)

    # PRUEBA 4: un retorno repetido no vuelve a confirmar el pago.

    @patch("finanzas.views.obtener_transaccion_webpay")
    def test_retorno_repetido_no_confirma_dos_veces(
        self, obtener_transaccion
    ):
        pago = self.crear_pago(
            estado=Pago.Estado.CONFIRMADO,
        )

        self.cuota.estado = Cuota.Estado.PAGADA
        self.cuota.save(
            update_fields=["estado", "actualizado_en"]
        )

        response = self.client.post(
            reverse("finanzas:retorno_webpay"),
            {"token_ws": pago.token_ws},
        )

        self.assertEqual(response.status_code, 200)
        obtener_transaccion.return_value.commit.assert_not_called()

        self.assertEqual(
            Pago.objects.filter(
                cuota=self.cuota,
                estado=Pago.Estado.CONFIRMADO,
            ).count(),
            1,
        )

    # PRUEBA 5: otro usuario no puede iniciar un pago ajeno.

    def test_usuario_no_autorizado_no_puede_iniciar_pago(self):
        otro_usuario = Usuario.objects.create_user(
            rut="22222222-2",
            password="OtraClaveSegura-2026",
        )

        self.client.force_login(otro_usuario)

        response = self.client.post(
            reverse(
                "finanzas:iniciar_pago",
                args=[self.cuota.pk],
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Pago.objects.filter(cuota=self.cuota).count(),
            0,
        )
        self.assertEqual(
            self.cuota.estado,
            Cuota.Estado.PENDIENTE,
        )

    # PRUEBA 6: una cancelación deja la cuota pendiente.

    def test_cancelacion_deja_cuota_pendiente(self):
        pago = self.crear_pago()

        response = self.client.post(
            reverse("finanzas:retorno_webpay"),
            {"TBK_TOKEN": pago.token_ws},
        )

        pago.refresh_from_db()
        self.cuota.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pago.estado, Pago.Estado.ANULADO)
        self.assertEqual(
            self.cuota.estado,
            Cuota.Estado.PENDIENTE,
        )

    # PRUEBA 7: un intento reciente no reutiliza automáticamente el token.

    @patch("finanzas.views.obtener_transaccion_webpay")
    def test_reanudar_pago_reciente_no_reutiliza_el_token(
        self, obtener_transaccion
    ):
        pago = self.crear_pago()

        obtener_transaccion.return_value.status.return_value = {
            "status": "INITIALIZED",
            "response_code": None,
            "amount": int(pago.monto),
            "buy_order": pago.orden_compra,
            "session_id": pago.session_id,
        }

        response = self.client.post(
            reverse(
                "finanzas:reanudar_pago",
                args=[self.cuota.pk],
            )
        )

        pago.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            pago.estado,
            Pago.Estado.INICIADO,
        )
        self.assertEqual(
            Pago.objects.filter(cuota=self.cuota).count(),
            1,
        )
        obtener_transaccion.return_value.create.assert_not_called()

    # PRUEBA 8: un intento antiguo genera una nueva orden y token.

    @patch("finanzas.views.obtener_transaccion_webpay")
    def test_reanudar_pago_expirado_crea_un_nuevo_intento(
        self, obtener_transaccion
    ):
        # 1. Crear el intento de pago original.
        pago_anterior = self.crear_pago()

        # Simular que el intento se inició hace seis minutos.
        pago_anterior.creado_en = (
    timezone.now() - timedelta(minutes=6)
)
        pago_anterior.save(update_fields=["creado_en"])
        pago_anterior.refresh_from_db()

        self.assertGreaterEqual(
    timezone.now() - pago_anterior.creado_en,
    timedelta(minutes=5),
    "La prueba debe preparar un intento de pago de al menos cinco minutos.",
)

        # 2. Simular la consulta del estado en Transbank.
        obtener_transaccion.return_value.status.return_value = {
            "status": "INITIALIZED",
            "response_code": None,
            "amount": int(pago_anterior.monto),
            "buy_order": pago_anterior.orden_compra,
            "session_id": pago_anterior.session_id,
        }

        # 3. Simular la creación de una nueva transacción.
        obtener_transaccion.return_value.create.return_value = {
            "token": "token-renovado-prueba",
            "url": (
                "https://webpay3gint.transbank.cl/"
                "webpayserver/init_transaction.cgi"
            ),
        }

        # 4. Solicitar la reanudación mediante la vista de Django.
        response = self.client.post(
            reverse(
                "finanzas:reanudar_pago",
                args=[self.cuota.pk],
            )
        )

        # 5. Consultar los registros guardados en la base de pruebas.
        pago_anterior.refresh_from_db()

        pagos_registrados = list(
            Pago.objects.filter(cuota=self.cuota).values_list(
                "id",
                "estado",
                "creado_en",
            )
        )

        mensajes = list(
            getattr(response.wsgi_request, "_messages", [])
        )

        # 6. Comprobar que se conserva el intento anterior
        # y que se crea uno nuevo.
        self.assertEqual(
            len(pagos_registrados),
            2,
            msg=(
                "Se esperaba conservar el intento anterior y crear otro. "
                f"HTTP={response.status_code}; "
                f"URL={getattr(response, 'url', None)}; "
                f"pagos={pagos_registrados}; "
                f"mensajes={[str(m) for m in mensajes]}"
            ),
        )

        # 7. Recuperar el nuevo intento.
        nuevo_pago = Pago.objects.exclude(
            pk=pago_anterior.pk
        ).get(cuota=self.cuota)

        self.cuota.refresh_from_db()

        # 8. Verificar el resultado.
        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            pago_anterior.estado,
            Pago.Estado.EXPIRADO,
        )

        self.assertEqual(
            nuevo_pago.estado,
            Pago.Estado.INICIADO,
        )

        self.assertEqual(
            nuevo_pago.token_ws,
            "token-renovado-prueba",
        )

        self.assertNotEqual(
            nuevo_pago.orden_compra,
            pago_anterior.orden_compra,
        )

        self.assertEqual(
            self.cuota.estado,
            Cuota.Estado.PENDIENTE,
        )

        obtener_transaccion.return_value.status.assert_called_once_with(
            pago_anterior.token_ws
        )

        obtener_transaccion.return_value.create.assert_called_once()



class ResumenMorosidadTests(TestCase):

    def crear_jugador(self, rut, nombres):
        return Jugador.objects.create(
            rut=rut,
            nombres=nombres,
            apellidos="Prueba",
            fecha_nacimiento=date(2012, 5, 10),
            rama=Jugador.Rama.VARONES,
            estado=Jugador.Estado.ACTIVO,
        )

    def crear_cuotas_vencidas(self, jugador, periodos):
        for periodo in periodos:
            Cuota.objects.create(
                jugador=jugador,
                concepto="Mensualidad",
                periodo=periodo,
                monto=Decimal("15000"),
                fecha_vencimiento=periodo.replace(day=10),
                estado=Cuota.Estado.PENDIENTE,
            )

    def test_lista_morosos_y_excluye_beca_vigente(self):
        hoy = timezone.localdate()

        moroso = self.crear_jugador("22333444-K", "Jugador Uno")
        becado = self.crear_jugador("22333445-8", "Jugador Dos")
        un_mes = self.crear_jugador("22333446-6", "Jugador Tres")

        periodos = [
            date(2025, 1, 1),
            date(2025, 2, 1),
        ]

        self.crear_cuotas_vencidas(moroso, periodos)
        self.crear_cuotas_vencidas(becado, periodos)
        self.crear_cuotas_vencidas(un_mes, periodos[:1])

        Beca.objects.create(
            jugador=becado,
            fecha_inicio=hoy - timedelta(days=30),
        )

        resultado = obtener_resumen_morosidad(fecha=hoy)

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["jugador"].pk, moroso.pk)
        self.assertEqual(resultado[0]["meses_impagos"], 2)
        self.assertEqual(resultado[0]["deuda_vencida"], Decimal("30000"))

    def test_beca_vencida_no_excluye_del_listado(self):
        hoy = timezone.localdate()
        jugador = self.crear_jugador("22333447-4", "Jugador Cuatro")

        self.crear_cuotas_vencidas(
            jugador,
            [date(2025, 1, 1), date(2025, 2, 1)],
        )

        Beca.objects.create(
            jugador=jugador,
            fecha_inicio=hoy - timedelta(days=220),
        )

        resultado = obtener_resumen_morosidad(fecha=hoy)

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["jugador"].pk, jugador.pk)
