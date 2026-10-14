from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    model = Usuario
    ordering = ["nombre"]
    list_display = [
        "email",
        "nombre",
        "id_almacen",
        "rol",
        "is_staff",
        "is_active",
        "fecha_creacion",
    ]
    list_filter = ["id_almacen", "rol", "is_staff", "is_active"]
    search_fields = ["email", "nombre"]
    readonly_fields = ["fecha_creacion", "last_login"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Datos personales", {"fields": ("id_almacen", "nombre", "rol")}),
        (
            "Permisos",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Fechas", {"fields": ("last_login", "fecha_creacion")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("id_almacen", "email", "nombre", "rol", "password1", "password2"),
            },
        ),
    )
