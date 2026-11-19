from html import escape
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generar_pdf_nomina(nomina):
    """Devuelve los bytes del PDF de la nómina."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"Nómina {nomina.titulo}",
    )
    estilos = getSampleStyleSheet()

    datos_partido = (
        f"<b>Categoría:</b> {escape(str(nomina.categoria))}<br/>"
        f"<b>Fecha:</b> {nomina.fecha:%d/%m/%Y}<br/>"
    )
    if nomina.lugar:
        datos_partido += f"<b>Lugar:</b> {escape(nomina.lugar)}<br/>"

    contenido = [
        Paragraph("Club Deportivo Ayllu Basket", estilos["Title"]),
        Paragraph(f"Nómina de partido: {escape(nomina.titulo)}", estilos["Heading2"]),
        Paragraph(datos_partido, estilos["Normal"]),
        Spacer(1, 0.5 * cm),
    ]

    filas = [["N°", "Jugador", "RUT", "Fecha nac."]]
    for n, integrante in enumerate(nomina.integrantes.select_related("jugador"), start=1):
        j = integrante.jugador
        filas.append([
            str(n),
            f"{j.apellidos}, {j.nombres}",
            j.rut,
            j.fecha_nacimiento.strftime("%d/%m/%Y"),
        ])

    tabla = Table(filas, colWidths=[1.2 * cm, 8 * cm, 3.5 * cm, 3 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17171A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E1DFDB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F3F1")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    contenido.append(tabla)

    if nomina.observaciones:
        contenido += [Spacer(1, 0.5 * cm), Paragraph(f"<b>Observaciones:</b> {escape(nomina.observaciones)}", estilos["Normal"])]

    responsable = nomina.creado_por.get_full_name() or nomina.creado_por.rut
    contenido += [
        Spacer(1, 1.5 * cm),
        Paragraph(f"Generada por: {escape(responsable)} — {timezone.localtime(nomina.creado_en):%d/%m/%Y %H:%M}", estilos["Normal"]),
        Spacer(1, 1.5 * cm),
        Paragraph("_______________________________<br/>Firma entrenador responsable", estilos["Normal"]),
    ]

    doc.build(contenido)
    return buffer.getvalue()