(function () {
    "use strict";

    const input = document.getElementById("input-codigo");
    const contenedorResultado = document.getElementById("resultado");
    const urlBuscar = contenedorResultado.dataset.urlBuscar;
    const urlCrear = contenedorResultado.dataset.urlCrear;
    const urlSumarStockBase = contenedorResultado.dataset.urlSumarStockBase;

    function enfocarInput() {
        input.value = "";
        input.focus();
    }

    function obtenerCookie(nombre) {
        const valor = document.cookie
            .split("; ")
            .find((fila) => fila.startsWith(nombre + "="));
        return valor ? decodeURIComponent(valor.split("=")[1]) : null;
    }

    function renderExistente(producto) {
        const plantilla = document.getElementById("plantilla-existente").content.cloneNode(true);
        plantilla.querySelector('[data-campo="nombre"]').textContent = producto.nombre;
        plantilla.querySelector('[data-campo="categoria"]').textContent = producto.categoria;
        plantilla.querySelector('[data-campo="precio"]').textContent = producto.precio;
        plantilla.querySelector('[data-campo="stock_actual"]').textContent = producto.stock_actual;
        plantilla.querySelector('[data-campo="stock_minimo"]').textContent = producto.stock_minimo;

        if (producto.stock_bajo) {
            plantilla.querySelector('[data-campo="aviso_stock_bajo"]').hidden = false;
        }

        const form = plantilla.querySelector("[data-form-sumar-stock]");
        form.action = urlSumarStockBase.replace("/0/", "/" + producto.id_producto + "/");
        form.addEventListener("submit", function () {
            // Deja que el form haga un POST normal (recarga la página con el mensaje
            // de confirmación); tras volver, el input ya queda enfocado de nuevo.
        });

        contenedorResultado.replaceChildren(plantilla);
    }

    function renderNoExiste(codigo) {
        const plantilla = document.getElementById("plantilla-no-existe").content.cloneNode(true);
        plantilla.querySelector('[data-campo="codigo"]').textContent = codigo;
        const enlace = plantilla.querySelector('[data-campo="enlace-nuevo"]');
        enlace.href = urlCrear + "?codigo=" + encodeURIComponent(codigo);
        contenedorResultado.replaceChildren(plantilla);
    }

    async function buscarCodigo(codigo) {
        const respuesta = await fetch(urlBuscar + "?codigo=" + encodeURIComponent(codigo), {
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const datos = await respuesta.json();
        if (datos.existe) {
            renderExistente(datos.producto);
        } else {
            renderNoExiste(codigo);
        }
    }

    input.addEventListener("keydown", function (evento) {
        if (evento.key !== "Enter") {
            return;
        }
        evento.preventDefault();
        const codigo = input.value.trim();
        if (!codigo) {
            return;
        }
        buscarCodigo(codigo);
    });

    enfocarInput();
})();
