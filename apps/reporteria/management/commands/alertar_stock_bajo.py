from apps.reporteria.servicios import alertar_stock_bajo

from ._base import ComandoPorAlmacen


class Command(ComandoPorAlmacen):
    help = "CU-05: deja en el panel una alerta por almacén con productos en o bajo el mínimo."

    def handle(self, *args, **opciones):
        fecha = self.fecha(opciones)
        for almacen in self.almacenes():
            alerta, creada = alertar_stock_bajo(almacen, fecha)
            if alerta is None:
                estado = "sin productos bajo el mínimo, no se genera alerta"
            elif creada:
                estado = f"alerta creada: {alerta.mensaje}"
            else:
                estado = "la alerta de hoy ya existía"
            self.stdout.write(f"{almacen} ({almacen.pk}): {estado}")
