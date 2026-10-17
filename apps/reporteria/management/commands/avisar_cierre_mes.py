from apps.reporteria.servicios import avisar_cierre_mes

from ._base import ComandoPorAlmacen


class Command(ComandoPorAlmacen):
    help = (
        "Cierre de mes: avisa en el panel que el reporte del mes anterior está "
        "disponible. Sólo avisa; el reporte se calcula al abrirlo."
    )

    def handle(self, *args, **opciones):
        fecha = self.fecha(opciones)
        for almacen in self.almacenes():
            alerta, creada = avisar_cierre_mes(almacen, fecha)
            if alerta is None:
                estado = "el mes anterior no tuvo ventas, no hay nada que avisar"
            elif creada:
                estado = f"aviso creado: {alerta.mensaje}"
            else:
                estado = "el aviso de ese mes ya existía"
            self.stdout.write(f"{almacen} ({almacen.pk}): {estado}")
