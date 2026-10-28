from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import permisos, services
from .forms import (
    ActaNuevaForm, DocumentoNuevoForm, MiembroForm, SancionAnulacionForm,
    SancionCorreccionForm, SancionNuevaForm, SancionResolucionForm,
    VersionActaForm, VersionDocumentoForm,
)
from .models import Acta, DocumentoNormativo, Sancion, VersionActa, VersionDocumentoNormativo
from .validators import validar_pdf


def acceso_requerido(comprobar):
    def decorar(vista):
        @never_cache
        @login_required
        @wraps(vista)
        def protegida(request, *args, **kwargs):
            if not comprobar(request.user):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return protegida
    return decorar


def _error_formulario(form, error):
    if isinstance(error, ValidationError):
        for mensaje in error.messages:
            form.add_error(None, mensaje)
    else:
        form.add_error(None, "La versión o el código ya existe, o hubo un cambio simultáneo. Actualiza y vuelve a intentarlo.")


@acceso_requerido(permisos.puede_acceder)
@require_GET
def inicio(request):
    return render(request, "institucional/inicio.html")


def _normativa_visible(usuario):
    versiones = VersionDocumentoNormativo.objects.select_related("documento")
    if permisos.puede_gestionar_normativa(usuario):
        return versiones
    versiones = versiones.filter(
        estado=VersionDocumentoNormativo.Estado.VIGENTE,
        vigente_desde__lte=timezone.localdate(), publicado_en__lte=timezone.now(),
    )
    if not permisos.puede_consultar_normativa(usuario):
        versiones = versiones.filter(visibilidad=VersionDocumentoNormativo.Visibilidad.PUBLICO)
    return versiones


@never_cache
@require_GET
def documentos(request):
    versiones = _normativa_visible(request.user)
    return render(request, "institucional/documentos_lista.html", {"versiones": versiones.order_by("documento__codigo", "-numero")})


@never_cache
@require_GET
def documento_detalle(request, pk):
    versiones = _normativa_visible(request.user).filter(documento_id=pk).select_related("publicado_por")
    lista = list(versiones)
    if not lista:
        raise Http404
    historial = _historial("VersionDocumentoNormativo", lista) if permisos.puede_gestionar_normativa(request.user) else []
    return render(request, "institucional/documento_detalle.html", {"documento": lista[0].documento, "versiones": lista, "historial": historial})


@acceso_requerido(permisos.puede_gestionar_normativa)
@require_http_methods(["GET", "POST"])
def documento_nuevo(request):
    form = DocumentoNuevoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            version = services.crear_documento(usuario=request.user, codigo=form.cleaned_data["codigo"], tipo=form.cleaned_data["tipo"], datos=form.cleaned_data, archivo=form.cleaned_data.get("archivo"))
        except (ValidationError, IntegrityError) as error:
            _error_formulario(form, error)
        else:
            messages.success(request, "Borrador creado. Revisa y publica cuando esté listo.")
            return redirect("institucional:documento_detalle", pk=version.documento_id)
    return render(request, "institucional/formulario.html", {"form": form, "titulo": "Nuevo documento normativo"})


@acceso_requerido(permisos.puede_gestionar_normativa)
@require_http_methods(["GET", "POST"])
def documento_version(request, pk=None, version_id=None):
    version = get_object_or_404(VersionDocumentoNormativo, pk=version_id) if version_id else None
    documento = version.documento if version else get_object_or_404(DocumentoNormativo, pk=pk)
    if version and version.estado != version.Estado.BORRADOR:
        raise Http404
    inicial = {campo: getattr(version, campo) for campo in ("titulo", "version", "visibilidad", "fecha_documento", "vigente_desde", "motivo_cambio")} if version else {}
    form = VersionDocumentoForm(request.POST or None, request.FILES or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        try:
            if version:
                services.editar_documento(usuario=request.user, version_id=version.pk, datos=form.cleaned_data, archivo=form.cleaned_data.get("archivo"))
            else:
                services.nueva_version_documento(usuario=request.user, documento_id=documento.pk, datos=form.cleaned_data, archivo=form.cleaned_data.get("archivo"))
        except (ValidationError, IntegrityError) as error:
            _error_formulario(form, error)
        else:
            messages.success(request, "Borrador guardado.")
            return redirect("institucional:documento_detalle", pk=documento.pk)
    return render(request, "institucional/formulario.html", {"form": form, "titulo": "Editar borrador" if version else "Nueva versión normativa", "archivo_actual": version.archivo_nombre if version else ""})


@acceso_requerido(permisos.puede_publicar_normativa)
@require_POST
def documento_publicar(request, version_id):
    version = get_object_or_404(VersionDocumentoNormativo, pk=version_id)
    try:
        services.publicar_documento(usuario=request.user, version_id=version.pk)
    except (ValidationError, IntegrityError) as error:
        messages.error(request, " ".join(error.messages) if isinstance(error, ValidationError) else "Otra versión cambió. Actualiza la página.")
    else:
        messages.success(request, "Documento publicado como versión vigente.")
    return redirect("institucional:documento_detalle", pk=version.documento_id)


def _descargar(version):
    if not version.archivo:
        raise Http404
    try:
        archivo = version.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("Archivo no disponible.")
    try:
        datos = validar_pdf(archivo)
        if datos["sha256"] != version.archivo_sha256:
            raise ValidationError("Archivo alterado.")
    except ValidationError:
        archivo.close()
        raise Http404("Archivo no disponible.")
    respuesta = FileResponse(archivo, as_attachment=True, filename=f"documento-{version.pk}.pdf", content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta


@never_cache
@require_GET
def documento_descargar(request, version_id):
    versiones = _normativa_visible(request.user)
    return _descargar(get_object_or_404(versiones, pk=version_id))


@acceso_requerido(permisos.puede_gestionar_miembros)
@require_http_methods(["GET", "POST"])
def miembros(request):
    from usuarios.models import Usuario

    form = MiembroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.autorizar_miembro(usuario=request.user, destinatario=form.cleaned_data["destinatario"], autorizar=form.cleaned_data["accion"] == "autorizar", motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _error_formulario(form, error)
        else:
            messages.success(request, "Autorización actualizada y registrada.")
            return redirect("institucional:miembros")
    cuentas = Usuario.objects.filter(groups__name=permisos.GRUPO_MIEMBROS)
    return render(request, "institucional/miembros.html", {"form": form, "cuentas": cuentas})


def _historial(entidad, versiones):
    from usuarios.models import Auditoria

    return [{"fecha": registro.fecha, "actor": registro.usuario,
             "accion": registro.accion.replace("_", " ").capitalize()}
            for registro in Auditoria.objects.filter(entidad=entidad, entidad_id__in=[v.pk for v in versiones]).select_related("usuario")]


@acceso_requerido(permisos.puede_consultar_actas)
@require_GET
def actas(request):
    versiones = VersionActa.objects.select_related("acta")
    if not permisos.puede_gestionar_actas(request.user):
        versiones = versiones.filter(estado=VersionActa.Estado.PUBLICADA)
    return render(request, "institucional/actas_lista.html", {"versiones": versiones.order_by("-fecha_reunion", "acta_id", "-numero")})


@acceso_requerido(permisos.puede_consultar_actas)
@require_GET
def acta_detalle(request, pk):
    versiones = VersionActa.objects.filter(acta_id=pk).select_related("acta", "publicado_por")
    if not permisos.puede_gestionar_actas(request.user):
        versiones = versiones.filter(estado=VersionActa.Estado.PUBLICADA)
    lista = list(versiones)
    if not lista:
        raise Http404
    historial = _historial("VersionActa", lista) if permisos.puede_gestionar_actas(request.user) else []
    return render(request, "institucional/acta_detalle.html", {"acta": lista[0].acta, "versiones": lista, "historial": historial})


@acceso_requerido(permisos.puede_gestionar_actas)
@require_http_methods(["GET", "POST"])
def acta_nueva(request):
    form = ActaNuevaForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            version = services.crear_acta(usuario=request.user, codigo=form.cleaned_data["codigo"], datos=form.cleaned_data, archivo=form.cleaned_data.get("archivo"))
        except (ValidationError, IntegrityError) as error:
            _error_formulario(form, error)
        else:
            messages.success(request, "Borrador de acta creado.")
            return redirect("institucional:acta_detalle", pk=version.acta_id)
    return render(request, "institucional/formulario.html", {"form": form, "titulo": "Nueva acta"})


@acceso_requerido(permisos.puede_gestionar_actas)
@require_http_methods(["GET", "POST"])
def acta_version(request, pk=None, version_id=None):
    version = get_object_or_404(VersionActa, pk=version_id) if version_id else None
    acta = version.acta if version else get_object_or_404(Acta, pk=pk)
    if version and version.estado != version.Estado.BORRADOR:
        raise Http404
    referencia = version or acta.versiones.first()
    inicial = {campo: getattr(referencia, campo) for campo in ("titulo", "fecha_reunion", "acuerdos")} if referencia else {}
    inicial["motivo_cambio"] = version.motivo_cambio if version else ""
    form = VersionActaForm(request.POST or None, request.FILES or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        try:
            if version:
                services.editar_acta(usuario=request.user, version_id=version.pk, datos=form.cleaned_data, archivo=form.cleaned_data.get("archivo"))
            else:
                services.nueva_version_acta(usuario=request.user, acta_id=acta.pk, datos=form.cleaned_data, archivo=form.cleaned_data.get("archivo"))
        except (ValidationError, IntegrityError) as error:
            _error_formulario(form, error)
        else:
            messages.success(request, "Borrador de acta guardado.")
            return redirect("institucional:acta_detalle", pk=acta.pk)
    return render(request, "institucional/formulario.html", {"form": form, "titulo": "Editar borrador de acta" if version else "Corregir acta mediante nueva versión", "archivo_actual": version.archivo_nombre if version else ""})


@acceso_requerido(permisos.puede_publicar_actas)
@require_POST
def acta_publicar(request, version_id):
    version = get_object_or_404(VersionActa, pk=version_id)
    try:
        services.publicar_acta(usuario=request.user, version_id=version.pk)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Acta publicada.")
    return redirect("institucional:acta_detalle", pk=version.acta_id)


@acceso_requerido(permisos.puede_consultar_actas)
@require_GET
def acta_descargar(request, version_id):
    versiones = VersionActa.objects.all()
    if not permisos.puede_gestionar_actas(request.user):
        versiones = versiones.filter(estado=VersionActa.Estado.PUBLICADA)
    return _descargar(get_object_or_404(versiones, pk=version_id))


@acceso_requerido(permisos.puede_consultar_sanciones)
@require_GET
def sanciones(request):
    return render(request, "institucional/sanciones_lista.html", {"sanciones": Sancion.objects.select_related("jugador")})


@acceso_requerido(permisos.puede_consultar_sanciones)
@require_GET
def sancion_detalle(request, pk):
    get_object_or_404(Sancion, pk=pk)
    sancion = services.consultar_sancion(usuario=request.user, sancion_id=pk)
    return render(request, "institucional/sancion_detalle.html", {"sancion": sancion, "eventos": sancion.eventos.select_related("actor")})


@acceso_requerido(permisos.puede_registrar_sanciones)
@require_http_methods(["GET", "POST"])
def sancion_nueva(request):
    form = SancionNuevaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            sancion = services.registrar_sancion(usuario=request.user, **form.cleaned_data)
        except ValidationError as error:
            _error_formulario(form, error)
        else:
            messages.success(request, "Expediente registrado en el área del Comité.")
            return redirect("institucional:sancion_detalle", pk=sancion.pk)
    return render(request, "institucional/formulario.html", {"form": form, "titulo": "Registrar sanción"})


@acceso_requerido(permisos.puede_consultar_sanciones)
@require_http_methods(["GET", "POST"])
def sancion_accion(request, pk, accion):
    corregir = accion == "corregir"
    services.exigir(permisos.puede_corregir_sanciones(request.user) if corregir else permisos.puede_resolver_sanciones(request.user))
    sancion = get_object_or_404(Sancion.objects.select_related("jugador"), pk=pk)
    if sancion.estado == "ANULADA" or (accion == "resolver" and sancion.estado != "REGISTRADA"):
        raise Http404
    clases = {"corregir": SancionCorreccionForm, "resolver": SancionResolucionForm, "anular": SancionAnulacionForm}
    inicial = {"revision": sancion.revision}
    if corregir:
        inicial.update(jugador=sancion.jugador, fecha=sancion.fecha, motivo=sancion.motivo, resolucion=sancion.resolucion)
    form = clases[accion](request.POST or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        operacion = {"corregir": services.corregir_sancion, "resolver": services.resolver_sancion, "anular": services.anular_sancion}[accion]
        try:
            operacion(usuario=request.user, sancion_id=pk, **form.cleaned_data)
        except ValidationError as error:
            _error_formulario(form, error)
        else:
            messages.success(request, "Cambio registrado en la bitácora privada.")
            return redirect("institucional:sancion_detalle", pk=pk)
    titulos = {"corregir": "Corregir expediente", "resolver": "Resolver expediente", "anular": "Anular expediente"}
    return render(request, "institucional/formulario.html", {"form": form, "titulo": titulos[accion]})
