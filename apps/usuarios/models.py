from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from apps.almacenes.aislamiento import ModeloDeAlmacen


class RolUsuario(models.TextChoices):
    ADMIN = "admin", "Administrador"
    VENDEDOR = "vendedor", "Vendedor"


class UsuarioManager(BaseUserManager):
    """
    Manager sin aislamiento: lo usan la autenticación (busca por email antes de saber
    el almacén) y `createsuperuser`. Las consultas de la aplicación usan `objects`.
    """

    use_in_migrations = True

    def create_user(self, email, nombre, password=None, **extra_fields):
        if not email:
            raise ValueError("El usuario debe tener un email")
        if not extra_fields.get("id_almacen") and not extra_fields.get("id_almacen_id"):
            raise ValueError("El usuario debe pertenecer a un almacén")
        email = self.normalize_email(email)
        usuario = self.model(email=email, nombre=nombre, **extra_fields)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, email, nombre, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("rol", RolUsuario.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("El superusuario debe tener is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("El superusuario debe tener is_superuser=True")

        # createsuperuser entrega el id del almacén como número.
        if isinstance(extra_fields.get("id_almacen"), int):
            extra_fields["id_almacen_id"] = extra_fields.pop("id_almacen")
        return self.create_user(email, nombre, password, **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin, ModeloDeAlmacen):
    """
    Usuario de un almacén (administrador o vendedor).

    Columnas del modelo físico: id_usuario, id_almacen, nombre, email, hash_password,
    rol, fecha_creacion. Los atributos Python `id` y `password` se mantienen porque los
    exige la maquinaria de autenticación de Django; is_active, is_staff, is_superuser y
    last_login son infraestructura de Django (convención §10 del brief).
    """

    id = models.BigAutoField(primary_key=True, db_column="id_usuario")
    nombre = models.CharField(max_length=120)
    email = models.EmailField(max_length=150)
    password = models.CharField(max_length=128, db_column="hash_password")
    rol = models.CharField(
        max_length=10,
        choices=RolUsuario.choices,
        default=RolUsuario.VENDEDOR,
    )
    fecha_creacion = models.DateTimeField(default=timezone.now, db_default=Now())

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    sin_aislamiento = UsuarioManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nombre", "id_almacen"]

    class Meta:
        db_table = "usuario"
        default_manager_name = "sin_aislamiento"
        ordering = ["nombre"]
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        constraints = [
            models.UniqueConstraint(fields=["email"], name="uq_usuario_email"),
            models.CheckConstraint(
                condition=models.Q(rol__in=RolUsuario.values), name="ck_usuario_rol"
            ),
        ]
        indexes = [models.Index(fields=["id_almacen"], name="ix_usuario_almacen")]

    def __str__(self):
        return f"{self.nombre} ({self.email})"

    def get_full_name(self):
        return self.nombre

    def get_short_name(self):
        return self.nombre

    @property
    def es_admin(self):
        return self.rol == RolUsuario.ADMIN

    @property
    def es_vendedor(self):
        return self.rol == RolUsuario.VENDEDOR
