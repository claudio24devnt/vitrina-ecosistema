(function () {
    "use strict";

    const input = document.getElementById("input-codigo");
    const aviso = document.getElementById("aviso-escaneo");
    const carrito = document.getElementById("carrito");
    const filaVacia = document.getElementById("carrito-vacio");
    const totalVenta = document.getElementById("total-venta");
    const botonCobrar = document.getElementById("boton-cobrar");
    const botonVaciar = document.getElementById("boton-vaciar");
    const form = document.getElementById("form-venta");
    const urlBuscar = input.dataset.urlBuscar;

    // id_producto -> { fila, precio, stock }
    const items = new Map();

    function formatearPesos(monto) {
        return "$" + Math.round(monto).toLocaleString("es-CL");
    }

    function mostrarAviso(texto) {
        aviso.textContent = texto;
        aviso.hidden = !texto;
    }

    function enfocarInput() {
        input.value = "";
        input.focus();
    }

    function recalcular() {
        let total = 0;
        items.forEach(function (item) {
            const inputCantidad = item.fila.querySelector('input[name="cantidad"]');
            const cantidad = parseInt(inputCantidad.value, 10) || 0;
            const subtotal = cantidad * item.precio;
            total += subtotal;
            item.fila.querySelector('[data-campo="subtotal"]').textContent = formatearPesos(subtotal);

            const etiquetaStock = item.fila.querySelector('[data-campo="stock"]');
            etiquetaStock.hidden = cantidad <= item.stock;
            etiquetaStock.textContent = "SOLO HAY " + item.stock + " EN STOCK";
        });
        totalVenta.textContent = formatearPesos(total);
        filaVacia.hidden = items.size > 0;
        botonCobrar.disabled = items.size === 0;
    }

    function agregarProducto(producto) {
        const existente = items.get(producto.id_producto);
        if (existente) {
            const inputCantidad = existente.fila.querySelector('input[name="cantidad"]');
            inputCantidad.value = (parseInt(inputCantidad.value, 10) || 0) + 1;
            recalcular();
            return;
        }

        const plantilla = document.getElementById("plantilla-fila").content.cloneNode(true);
        const fila = plantilla.querySelector("tr");
        fila.querySelector('input[name="id_producto"]').value = producto.id_producto;
        fila.querySelector('[data-campo="nombre"]').textContent = producto.nombre;
        fila.querySelector('[data-campo="precio"]').textContent = formatearPesos(producto.precio);
        fila.querySelector('input[name="cantidad"]').addEventListener("input", recalcular);
        fila.querySelector('[data-accion="quitar"]').addEventListener("click", function () {
            items.delete(producto.id_producto);
            fila.remove();
            recalcular();
            enfocarInput();
        });

        items.set(producto.id_producto, {
            fila: fila,
            precio: parseFloat(producto.precio),
            stock: producto.stock_actual,
        });
        carrito.appendChild(fila);
        recalcular();
    }

    async function buscarCodigo(codigo) {
        try {
            const respuesta = await fetch(urlBuscar + "?codigo=" + encodeURIComponent(codigo), {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const datos = await respuesta.json();
            if (!datos.existe) {
                mostrarAviso("No hay ningún producto con el código " + codigo + ".");
                return;
            }
            if (datos.producto.stock_actual <= 0) {
                mostrarAviso("«" + datos.producto.nombre + "» no tiene stock disponible.");
                return;
            }
            mostrarAviso("");
            agregarProducto(datos.producto);
        } catch (error) {
            mostrarAviso("No se pudo buscar el producto. Revisá la conexión.");
        }
    }

    input.addEventListener("keydown", function (evento) {
        if (evento.key !== "Enter") {
            return;
        }
        evento.preventDefault();
        const codigo = input.value.trim();
        enfocarInput();
        if (codigo) {
            buscarCodigo(codigo);
        }
    });

    botonVaciar.addEventListener("click", function () {
        items.forEach(function (item) {
            item.fila.remove();
        });
        items.clear();
        mostrarAviso("");
        recalcular();
        enfocarInput();
    });

    form.addEventListener("submit", function () {
        // Evita doble registro si se presiona dos veces.
        botonCobrar.disabled = true;
    });

    recalcular();
    enfocarInput();
})();
