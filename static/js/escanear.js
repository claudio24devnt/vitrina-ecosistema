/*
 * Pantalla de escaneo (CU-01). El lector de código de barras funciona en modo HID:
 * "teclea" el código en el campo que tenga el foco y termina con Enter. Por eso el
 * campo de escaneo recupera el foco después de cada acción y al hacer clic en una
 * zona sin controles.
 */
(function () {
    "use strict";

    const campo = document.getElementById("campo-codigo");
    const resultado = document.getElementById("resultado");
    const urlBuscar = resultado.dataset.urlBuscar;
    const urlEntrada = resultado.dataset.urlEntrada;
    const urlNuevo = resultado.dataset.urlNuevo;
    const csrf = document.querySelector("input[name=csrfmiddlewaretoken]").value;
    let buscando = false;

    function formatearPesos(monto) {
        return "$" + Number(monto).toLocaleString("es-CL", { maximumFractionDigits: 0 });
    }

    function enfocarCampo() {
        campo.focus();
        campo.select();
    }

    function poner(raiz, nombre, texto) {
        raiz.querySelector('[data-campo="' + nombre + '"]').textContent = texto;
    }

    function mostrarAviso(tipo, texto) {
        const aviso = document.createElement("div");
        aviso.className = "alert alert-" + tipo;
        aviso.setAttribute("role", "alert");
        aviso.textContent = texto;
        resultado.replaceChildren(aviso);
    }

    function mostrarExistente(producto) {
        const tarjeta = document.getElementById("plantilla-existe").content.cloneNode(true);
        poner(tarjeta, "nombre", producto.nombre);
        poner(tarjeta, "categoria", producto.categoria || "Sin categoría");
        poner(tarjeta, "precio", formatearPesos(producto.precio));
        poner(tarjeta, "stock_actual", producto.stock_actual);
        poner(tarjeta, "stock_minimo", producto.stock_minimo);
        tarjeta.querySelector('[data-campo="aviso_stock_bajo"]').hidden = !producto.stock_bajo;

        const formulario = tarjeta.querySelector("[data-formulario-entrada]");
        formulario.addEventListener("submit", function (evento) {
            evento.preventDefault();
            sumarStock(producto, formulario);
        });
        resultado.replaceChildren(tarjeta);
    }

    function mostrarNoExiste(codigo) {
        const tarjeta = document.getElementById("plantilla-no-existe").content.cloneNode(true);
        poner(tarjeta, "codigo", codigo);
        tarjeta.querySelector('[data-campo="enlace-nuevo"]').href =
            urlNuevo + "?codigo=" + encodeURIComponent(codigo);
        resultado.replaceChildren(tarjeta);
    }

    async function buscar(codigo) {
        if (buscando) {
            return;
        }
        buscando = true;
        try {
            const respuesta = await fetch(urlBuscar.replace("CODIGO", encodeURIComponent(codigo)), {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            if (respuesta.status === 404) {
                mostrarNoExiste(codigo);
            } else if (respuesta.ok) {
                mostrarExistente((await respuesta.json()).producto);
            } else {
                mostrarAviso("danger", "No se pudo buscar el producto. Intenta de nuevo.");
            }
        } catch (error) {
            mostrarAviso("danger", "No hay conexión con el sistema. Revisa internet e intenta de nuevo.");
        } finally {
            buscando = false;
            enfocarCampo();
        }
    }

    async function sumarStock(producto, formulario) {
        const entrada = formulario.querySelector("input[type=number]");
        const error = formulario.querySelector('[data-campo="error"]');
        const cantidad = parseInt(entrada.value, 10);
        if (!Number.isInteger(cantidad) || cantidad < 1 || cantidad > 9999) {
            error.textContent = "Escribe una cantidad entre 1 y 9.999.";
            error.hidden = false;
            entrada.focus();
            return;
        }
        formulario.querySelector("button").disabled = true;
        try {
            const respuesta = await fetch(urlEntrada.replace("/0/", "/" + producto.id_producto + "/"), {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json",
                    "X-CSRFToken": csrf,
                },
                body: JSON.stringify({ cantidad: cantidad }),
            });
            const datos = await respuesta.json();
            if (!respuesta.ok) {
                error.textContent = datos.detalle || "No se pudo sumar el stock.";
                error.hidden = false;
                formulario.querySelector("button").disabled = false;
                return;
            }
            mostrarAviso(
                "success",
                "Se sumaron " + cantidad + " unidades a «" + datos.producto.nombre +
                    "». Stock actual: " + datos.producto.stock_actual + "."
            );
            campo.value = "";
            enfocarCampo();
        } catch (e) {
            error.textContent = "No hay conexión con el sistema. El stock no se modificó.";
            error.hidden = false;
            formulario.querySelector("button").disabled = false;
        }
    }

    campo.addEventListener("keydown", function (evento) {
        if (evento.key !== "Enter") {
            return;
        }
        evento.preventDefault();
        const codigo = campo.value.trim();
        if (codigo) {
            buscar(codigo);
        }
    });

    // Un clic fuera de los controles devuelve el foco al campo de escaneo.
    document.addEventListener("click", function (evento) {
        if (!evento.target.closest("input, button, a, select, textarea, label")) {
            enfocarCampo();
        }
    });

    // Al volver desde «código duplicado» la URL trae el código: se busca solo.
    if (campo.value.trim()) {
        buscar(campo.value.trim());
    } else {
        enfocarCampo();
    }
})();
