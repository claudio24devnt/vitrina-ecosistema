"""
Prueba de carga del punto de venta (§6 y §7: p95 < 2 s en la caja).

Simula vendedores que escanean productos y confirman ventas contra un servidor con
el almacén de demostración (DATOS FICTICIOS, `manage.py cargar_datos_ficticios`).
Nunca correrla contra un almacén real: registra ventas.

    pip install -r requirements-dev.txt
    python manage.py cargar_datos_ficticios --limpiar
    python manage.py runserver --noreload
    locust -f pruebas_carga/locustfile.py --host http://127.0.0.1:8000 \
        --headless -u 10 -r 2 -t 2m --csv pruebas_carga/resultado

Termina con código 1 si el p95 de las operaciones de caja supera los 2 s.
Ojo: `runserver` es un servidor de desarrollo de un proceso; la medición que vale
para el informe es contra el App Service (1.6), no contra el portátil.
"""

import os
import random
from datetime import datetime, timedelta, timezone

from locust import HttpUser, between, events, task

EMAIL = os.environ.get("CARGA_EMAIL", "vendedora@demo.ficticio.test")
CLAVE = os.environ.get("CARGA_CLAVE", "clave-ficticia-123")
CODIGOS = [f"20000000{i:05d}" for i in range(24)]  # los del almacén de demostración
P95_MAXIMO_MS = 2000
OPERACIONES_DE_CAJA = {"escanear", "confirmar venta"}


class Vendedor(HttpUser):
    wait_time = between(1, 4)  # una persona escaneando en el mesón

    def on_start(self):
        self.client.get("/cuentas/login/", name="login")
        respuesta = self.client.post(
            "/cuentas/login/",
            {
                "username": EMAIL,
                "password": CLAVE,
                "csrfmiddlewaretoken": self.client.cookies.get("csrftoken"),
            },
            name="login",
            allow_redirects=False,
        )
        if respuesta.status_code != 302:
            raise RuntimeError("No se pudo iniciar sesión: ¿cargaste los datos ficticios?")
        self.ids = []
        for codigo in CODIGOS:
            datos = self.client.get(f"/api/productos/codigo/{codigo}/", name="escanear")
            if datos.ok:
                self.ids.append(datos.json()["producto"]["id_producto"])

    @task(5)
    def escanear(self):
        self.client.get(f"/api/productos/codigo/{random.choice(CODIGOS)}/", name="escanear")

    @task(1)
    def vender(self):
        elegidos = random.sample(self.ids, k=random.randint(1, 4))
        inicio = datetime.now(timezone.utc) - timedelta(seconds=random.randint(20, 90))
        self.client.post(
            "/api/ventas/",
            json={
                "lineas": [{"id_producto": pk, "cantidad": 1} for pk in elegidos],
                "medio_pago": "efectivo",
                "hora_inicio": inicio.isoformat(),
                # La carga no evalúa el aviso de stock (6a); se confirma siempre.
                "confirmar_diferencias": True,
            },
            headers={"X-CSRFToken": self.client.cookies.get("csrftoken")},
            name="confirmar venta",
        )


@events.quitting.add_listener
def verificar_p95(environment, **_):
    for (nombre, _metodo), estadistica in environment.stats.entries.items():
        if nombre not in OPERACIONES_DE_CAJA or not estadistica.num_requests:
            continue
        p95 = estadistica.get_response_time_percentile(0.95)
        print(f"p95 {nombre}: {p95:.0f} ms ({estadistica.num_requests} solicitudes)")
        if p95 > P95_MAXIMO_MS:
            environment.process_exit_code = 1
