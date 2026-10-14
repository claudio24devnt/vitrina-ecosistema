from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class RolUsuario(models.TextChoices):
    ADMIN = "admin", "Administrador"
    VENDEDOR = "vendedor", "Vendedor"


class UsuarioManager(BaseUserManager):
    """Manager custom porque Usuario se autentica por email, no por username."""

    use_in_migrations = True

    def create_user(self, email, nombre, password=None, **extra_fields):
        if not email:
            raise ValueError("El usuario debe tener un email")
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

        return self.create_user(email, nombre, password, **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin):
    """
    Usuario del sistema (administrador o vendedor de un almacen).

    La PK y el campo de password usan db_column para respetar los nombres
    literales del diccionario de datos (id_usuario, hash_password) aunque
    los atributos Python se llaman `id` y `password`: son los nombres que
    espera la maquinaria de auth de Django (AbstractBaseUser, PermissionsMixin).
    """

    id = models.AutoField(primary_key=True, db_column="id_usuario")
    nombre = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128, db_column="hash_password")
    rol = models.CharField(
        max_length=20, choices=RolUsuario.choices, default=RolUsuario.VENDEDOR
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nombre"]

    objects = UsuarioManager()

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["nombre"]

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
