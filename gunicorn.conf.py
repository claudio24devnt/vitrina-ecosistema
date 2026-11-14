"""
Configuración de gunicorn. gunicorn la lee sola desde el directorio de trabajo, así
que vale para la línea de arranque del App Service (infra/modulos/appservice.bicep)
sin cambiarla; lo que esa línea pasa como opción (--workers, --timeout) manda.

Log de acceso a la salida estándar (App Service lo guarda en su log stream), con la
duración de cada solicitud en milisegundos, para poder investigar lentitud:

    2026-11-14T15:02:11 GET /api/productos/codigo/780.../ 200 1234B 42ms

Se registra la ruta sin la consulta (?mes=..., ?q=...) para no guardar búsquedas.
No se registran IP, cookies ni encabezados. La ruta de recuperación de contraseña
lleva un token de un solo uso que vence en una hora (PASSWORD_RESET_TIMEOUT), y
Django lo saca de la URL apenas se abre el enlace.
"""

accesslog = "-"
access_log_format = '%(t)s %(m)s %(U)s %(s)s %(B)sB %(M)sms "%(a)s"'
