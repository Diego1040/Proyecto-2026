# Proyecto-2026
# Plataforma Ayllu Basket

Plataforma web para el **Club Deportivo Ayllu Basket** (Arica): inscripción de jugadores, asistencia y nóminas, cuotas y pagos en línea con Webpay Plus, y gestión institucional del club.

Proyecto de Título · TIHI84 · Ingeniería en Informática · INACAP Sede Arica
Equipo: Miguel, Diego y Bryan · Docente: Rodrigo Tapia Santis

---

## Módulos

| Aplicación | Qué hace | HU |
| --- | --- | --- |
| `usuarios` | Inscripción, validación de solicitudes, activación y recuperación de cuentas con RUT, perfiles, categorías automáticas, importación desde Excel | HU-01 a HU-05, HU-19 |
| `deportivo` | Planificación de entrenamientos, asistencia, calendario, reporte de lesiones, nóminas con PDF e historial | HU-06 a HU-10, HU-20 |
| `finanzas` | Cuotas mensuales, pagos con Webpay Plus, pagos manuales, estado de cuenta y comprobantes PDF, becas, morosidad, inactividad temporal | HU-11 a HU-15 |
| `institucional` | Normativa con versiones, actas y Comité de Disciplina | HU-16 a HU-18 |

HU-23 (asistente virtual) fue excluida del alcance por indicación del docente.

## Tecnologías

- Python 3.12 o superior
- Django 6.1.1
- SQLite3
- transbank-sdk 6.1.0 (Webpay Plus, ambiente de integración)
- reportlab y pypdf (PDF), openpyxl (Excel)

## Instalación

```bash
git clone https://github.com/Diego1040/Proyecto-2026.git
cd Proyecto-2026

# Entorno virtual
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

## Preparar la base de datos

```bash
python manage.py migrate
python manage.py cargar_categorias          # 11 categorías de la temporada
python manage.py configurar_tesoreria       # grupo y permisos de Tesorería
python manage.py configurar_institucional   # grupos Secretaría y Comité de Disciplina
python manage.py createsuperuser            # se inicia sesión con RUT (ej. 11111111-1)
```

Los roles (Administración, Tesorería, Entrenador, Secretaría, Comité de Disciplina) se asignan como grupos desde `/admin/`.

## Uso

```bash
python manage.py runserver
```

Abrir http://127.0.0.1:8000/ e iniciar sesión con RUT y contraseña.

Tareas de administración:

```bash
# Generar las cuotas de un mes (con --simular solo calcula, no guarda)
python manage.py generar_cuotas_mensuales --periodo 2026-11 --simular
python manage.py generar_cuotas_mensuales --periodo 2026-11

# Importar jugadores desde la planilla del club (también existe la pantalla /administracion/importar-jugadores/)
python manage.py importar_jugadores planilla.xlsx --validar --temporada 2026
python manage.py importar_jugadores planilla.xlsx --importar --temporada 2026
```

### Pagos con Webpay Plus

La integración usa el **ambiente de integración de Transbank** con sus credenciales públicas de prueba, por lo que no se realizan cobros reales. Las tarjetas de prueba están en la [documentación de Transbank](https://www.transbankdevelopers.cl/documentacion/como_empezar#ambientes). Se necesita conexión a internet.

### Correos

En desarrollo los correos (activación de cuenta, recuperación de contraseña, aprobación o rechazo) se muestran en la consola donde corre `runserver`.

## Pruebas

```bash
python manage.py test
```

Resultado esperado: **424 pruebas, OK**. Para probar una aplicación:

```bash
python manage.py test deportivo
```

## Ramas

| Rama | Uso |
| --- | --- |
| `main` | Versión estable y entregable |
| `testing` | Integración de las ramas individuales para ejecutar el plan de pruebas |
| `feature/miguel`, `feature/diego`, `feature/bryan` | Trabajo de cada integrante |

## Datos personales

El sistema maneja datos de menores de edad (Ley 19.628 y Ley 21.719). **No se suben al repositorio** bases de datos (`*.sqlite3`) ni planillas del club (`*.xlsx`); ambas están en `.gitignore`. Para demostraciones se usan datos ficticios.

## Antes de producción

El despliegue propuesto es un VPS en AWS Lightsail (Ubuntu 24.04, Nginx, Gunicorn y HTTPS). Antes de publicar se debe mover `SECRET_KEY` a una variable de entorno, desactivar `DEBUG`, definir `ALLOWED_HOSTS`, configurar el servidor SMTP y usar las credenciales comerciales de Transbank.
