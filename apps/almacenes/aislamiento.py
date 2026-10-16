"""
Aislamiento multi-almacén (multi-tenant).

Regla: toda consulta de datos del dominio pasa por `Modelo.objects.del_almacen(almacen)`.
Una consulta por `objects` que no lo haga **falla** con ConsultaSinAlmacenError en vez de
devolver datos de todos los almacenes. No se acepta `filter(id_almacen=...)` como
sustituto: el filtro tiene que quedar marcado para que la regla sea verificable y
falle siempre del mismo modo, en todas las tablas.

Cada modelo tiene además un manager `sin_aislamiento`, que es el *default manager* de
Django. Lo usa la maquinaria interna (admin, autenticación, validación de unicidad,
managers de relaciones inversas como `venta.detalles`). En código de la aplicación sólo
se usa cuando la consulta es intencionalmente transversal (p. ej. el login, que busca
por email antes de saber el almacén); su nombre está elegido para que se note en una
revisión.
"""

from django.db import models


class ConsultaSinAlmacenError(RuntimeError):
    """Se ejecutó una consulta de datos del dominio sin `del_almacen(...)`."""


def _id_almacen(almacen):
    if almacen is None:
        raise ValueError("del_almacen() necesita un almacén (instancia o id), no None.")
    return getattr(almacen, "pk", almacen)


class AlmacenQuerySet(models.QuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._id_almacen_fijado = None

    def _clone(self):
        clon = super()._clone()
        clon._id_almacen_fijado = self._id_almacen_fijado
        return clon

    def del_almacen(self, almacen):
        id_almacen = _id_almacen(almacen)
        if self._id_almacen_fijado not in (None, id_almacen):
            raise ConsultaSinAlmacenError("La consulta ya estaba fijada a otro almacén.")
        # En Almacen la PK se llama id_almacen; en el resto es la FK. El filtro es el mismo.
        consulta = self.filter(id_almacen=id_almacen)
        consulta._id_almacen_fijado = id_almacen
        return consulta

    def _exigir_almacen(self):
        if self._id_almacen_fijado is None:
            raise ConsultaSinAlmacenError(
                f"Consulta sobre {self.model.__name__} sin del_almacen(...). "
                "Toda consulta del dominio debe filtrarse por almacén."
            )

    # Puntos por donde una consulta llega a la base de datos.
    def _fetch_all(self):
        if self._result_cache is None:
            self._exigir_almacen()
        super()._fetch_all()

    def iterator(self, *args, **kwargs):
        self._exigir_almacen()
        return super().iterator(*args, **kwargs)

    def count(self):
        self._exigir_almacen()
        return super().count()

    def exists(self):
        self._exigir_almacen()
        return super().exists()

    def contains(self, obj):
        self._exigir_almacen()
        return super().contains(obj)

    def aggregate(self, *args, **kwargs):
        self._exigir_almacen()
        return super().aggregate(*args, **kwargs)

    def update(self, **kwargs):
        self._exigir_almacen()
        return super().update(**kwargs)

    def delete(self):
        self._exigir_almacen()
        return super().delete()

    def in_bulk(self, *args, **kwargs):
        self._exigir_almacen()
        return super().in_bulk(*args, **kwargs)

    def bulk_update(self, *args, **kwargs):
        self._exigir_almacen()
        return super().bulk_update(*args, **kwargs)

    def explain(self, *args, **kwargs):
        self._exigir_almacen()
        return super().explain(*args, **kwargs)

    def create(self, **kwargs):
        # Crear no lee datos ajenos; si la consulta está fijada, el registro nace en ese
        # almacén y no se acepta que diga otro.
        if self._id_almacen_fijado is not None and self.model is not _modelo_almacen():
            indicado = kwargs.get("id_almacen")
            if indicado is not None and _id_almacen(indicado) != self._id_almacen_fijado:
                raise ConsultaSinAlmacenError("El registro indica un almacén distinto.")
            kwargs.pop("id_almacen", None)
            kwargs["id_almacen_id"] = self._id_almacen_fijado
        return super().create(**kwargs)


def _modelo_almacen():
    from .models import Almacen

    return Almacen


AlmacenManager = models.Manager.from_queryset(AlmacenQuerySet)


class ModeloAislado(models.Model):
    """
    Base de las tablas del modelo. Cada subclase concreta declara en su Meta
    `default_manager_name = "sin_aislamiento"` (ver docstring del módulo).
    """

    sin_aislamiento = models.Manager()
    objects = AlmacenManager()

    class Meta:
        abstract = True


class ModeloDeAlmacen(ModeloAislado):
    """Base de las tablas del dominio que pertenecen a un almacén (todas salvo `almacen`)."""

    id_almacen = models.ForeignKey(
        "almacenes.Almacen",
        on_delete=models.PROTECT,
        db_column="id_almacen",
        related_name="+",
        # Los índices con nombre del modelo físico cubren id_almacen donde corresponde.
        db_index=False,
    )

    class Meta:
        abstract = True
