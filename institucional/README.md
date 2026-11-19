# Institucional: HU17, HU16 y HU18

La aplicación agrega normativa, actas y expedientes del Comité. Sus seis modelos
son independientes de las reglas deportivas y económicas. Los expedientes y su
bitácora no están registrados en Django Admin.

## Preparación del entorno

Desde la raíz, usando el entorno virtual del proyecto:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

La migración inicial depende de `usuarios.0015_periodoinactividad`. Antes de
aplicar **cualquier migración a la base local**, obtener autorización y realizar
un respaldo. La implementación no aplica migraciones a `db.sqlite3`.
`0002_visibilidad_normativa` añade únicamente la visibilidad de cada versión
normativa: todos los documentos existentes permanecen INTERNOS.

Después de ese respaldo y autorización, aplicar las migraciones pendientes del
proyecto y configurar los grupos:

```powershell
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py configurar_institucional
```

El segundo comando es idempotente: añade permisos institucionales a los grupos
correspondientes, preserva los demás permisos y no asigna cuentas a ningún grupo.
Las pruebas utilizan una base de pruebas separada, no la base local.

## Roles y autorizaciones

Un responsable técnico puede asignar explícitamente los grupos mediante la
administración de usuarios existente. Operar las pantallas institucionales no
requiere `is_staff` ni `is_superuser`.

| Grupo | Operación |
| --- | --- |
| Administración | Borradores, clasificación y publicación normativa; autorizaciones excepcionales de consulta |
| Secretaría | Borradores y publicación de actas |
| Comité de Disciplina | Registro, consulta, corrección, resolución y anulación de expedientes |
| Tesorería y Entrenador | Consulta de actas publicadas y normativa vigente interna del club |
| Miembros autorizados | Vía excepcional de consulta conservada por compatibilidad; no es un requisito habitual |

La creación y publicación exigen el grupo correspondiente y su permiso
institucional; el bypass de superusuarios no se utiliza. La consulta documental
no concede acceso disciplinario: Administración sigue sin ver expedientes salvo
asignación expresa al Comité.

La inscripción pública no crea ni vincula cuentas. La aprobación crea una cuenta
inactiva y su activación exige autorización previa. La administración técnica
también puede crear cuentas activas y vincular perfiles: por eso `is_active`,
`activado_en`, `is_staff` o `is_superuser` aislados no acreditan pertenencia.

La consulta privada admite cuentas activas con un rol del club asignado por
personal autorizado (Administración, Secretaría, Tesorería, Entrenador o Comité),
o con credencial habilitada y perfil no pendiente legítimamente vinculado al mismo
RUT. Los apoderados necesitan además un vínculo actual, activo y con
`puede_gestionar=True`, a un jugador no pendiente. Los históricos de HU19 con esa
vinculación y habilitación no necesitan una nueva inscripción ni el grupo
Miembros autorizados. La inactividad deportiva no retira esta habilitación.

Se conservan las autorizaciones y la vía de aprobación anteriores. Administración
puede conceder o revocar la autorización excepcional en `/institucional/miembros/`,
con motivo y auditoría. No se eliminan grupos, permisos ni registros existentes.
Esa excepción no convierte perfiles pendientes en aprobados ni restaura vínculos
revocados. Revocarla sólo elimina la vía excepcional, no una pertenencia acreditada
por otro mecanismo.

## Normativa pública e interna

`/institucional/documentos/` y el enlace «Reglamentos y normativas» de la portada
permiten consultar sin sesión las versiones expresamente PÚBLICAS y vigentes.
Los documentos INTERNOS requieren habilitación del club; borradores e históricos
siguen reservados a Administración. La visibilidad se asigna a cada versión,
es INTERNA por defecto y se audita. Un borrador público no expone la versión
interna vigente. Para cambiar la clasificación de una publicación, crear una
nueva versión y publicarla. Las nuevas versiones vuelven a INTERNA por defecto,
incluso si la anterior era pública.

## Prueba manual

1. **HU17:** con Administración, entrar en `/institucional/documentos/`, crear
   un borrador y adjuntar un PDF. Comprobar el valor INTERNO predeterminado;
   seleccionar PÚBLICO expresamente y publicarlo. Sin sesión, entrar desde la
   portada y consultar/descargar esa versión. Un documento INTERNO no aparece
   para visitantes, ni se descarga mediante su URL. Crear otra versión con
   justificación: sólo la vigente puede ser pública; Administración conserva
   el historial y sus descargas. Ningún documento existente se publica al migrar.
2. **HU16:** con Secretaría, entrar en `/institucional/actas/`, crear un borrador
   con acuerdos y publicarlo, con PDF opcional. Corregir mediante una nueva
   versión justificada. Un usuario habilitado con cualquiera de los roles del
   club o un perfil legítimamente vinculado consulta las publicadas sin asignar
   Miembros autorizados; sólo Secretaría ve los borradores. Una cuenta activa
   que inicia sesión sin rol, perfil ni autorización válida no puede leer actas.
3. **HU18:** con el Comité, entrar en `/institucional/comite/`, registrar jugador,
   fecha y motivo. Corregir con justificación, resolver con resolución obligatoria
   o anular con resolución y justificación. Revisar la bitácora privada. Probar
   las mismas URLs con Administración o un superusuario sin el grupo: acceso
   denegado. Un expediente anulado se conserva sin nuevas modificaciones.

La navegación general y el panel ofrecen los accesos autorizados. El flujo de
Tesorería conserva su redirección. Las cuentas con acceso institucional reciben
en Tesorería un mensaje con enlace al área y disponen de un enlace de regreso a
Tesorería desde Institucional, también en navegación móvil.

La auditoría documental registra identificadores, acciones, campos modificados y
metadatos. Los acuerdos, títulos y justificaciones de las actas no se copian a
la auditoría general: se conservan en las versiones con su autorización propia.
Los registros previos de auditoría no se alteran automáticamente.

El selector del Comité conserva por ahora los jugadores históricos sin solicitud
aprobada, porque HU19 no crea esas solicitudes. Una restricción a pertenencia
aprobada requiere confirmar previamente cómo acreditar a esos históricos. No se
aplican filtros de elegibilidad deportiva ni se cambia el estado del jugador.

## PDF privados

`AYLLU_INSTITUCIONAL_PRIVATE_ROOT` configura un directorio absoluto permanente.
Por defecto se usa una carpeta hermana del repositorio, nunca se crea al ejecutar
checks o migraciones. Debe mantenerse fuera del proyecto, static, media público y
los temporales HU19. Configurar ACL del sistema operativo para el usuario del
servicio y respaldo del directorio junto con la base de datos.

Los archivos usan claves aleatorias y no tienen URL directa del almacenamiento.
La descarga comprueba la autorización en cada petición; permite acceso anónimo
sólo para una versión normativa PÚBLICA y vigente. Se entrega como adjunto y con
caché deshabilitada. Los PDF internos y las actas conservan su autorización privada.
La huella SHA-256 se comprueba antes de publicar o descargar el archivo.
Se validan extensión, estructura PDF, cifrado, acciones y adjuntos; límite por
defecto de 5 MiB y 200 páginas. Los límites son configurables mediante
`INSTITUCIONAL_PDF_MAX_BYTES` e `INSTITUCIONAL_PDF_MAX_PAGES`.

Configurar también el límite de petición en el servidor web. La validación
estructural no sustituye un análisis antimalware para despliegues de producción.
Las versiones publicadas no se sobrescriben mediante la aplicación. Una escritura
fallida descarta su archivo nuevo; la sustitución del PDF de un borrador sólo
elimina el archivo anterior después de confirmar la transacción.

La bitácora controla las operaciones de la aplicación; quien administra la base
de datos o el servidor mantiene acceso técnico. Las relaciones protegidas impiden
borrar físicamente jugadores o responsables referenciados por expedientes.

## Pendiente independiente para Diego

HU15 bloquea nóminas por morosidad. Según la decisión comunicada del club, deberían
utilizarse solamente alertas. Este conflicto debe revisarse fuera de HU16–HU18:
la implementación institucional no amplía, reutiliza ni modifica esa regla.
