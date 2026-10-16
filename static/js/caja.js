/*
 * Caja (CU-02). El lector HID "teclea" el código y termina con Enter, así que el
 * campo de escaneo recupera el foco después de cada acción.
 *
 * El navegador sólo arma la venta: el precio, el stock y el total los decide el
 * servidor en una sola transacción (POST /api/ventas/).
 */
(function () {
    "use strict";

    const raiz = document.getElementById("caja");
    const campo = document.getElementById("campo-codigo");
    const aviso = document.getElementById("aviso-escaneo");
    const cuerpo = document.getElementById("lineas");
    const sinLineas = document.getElementById("sin-lineas");
    const totalVista = document.getElementById("total");
    const botonCobrar = document.getElementById("boton-cobrar");
    const botonVaciar = document.getElementById("boton-vaciar");
    const panelAlta = document.getElementById("panel-alta");
    const formularioAlta = document.getElementById("formulario-alta");
    const panelDiferencias = document.getElementById("panel-diferencias");
    const confirmo = document.getElementById("confirmo-diferencias");
    const errorVenta = document.getElementById("error-venta");
    const csrf = document.querySelector("input[name=csrfmiddlewaretoken]").value;

    // id_producto -> { producto, cantidad, altaRapida, fila }
    const lineas = new Map();
    let horaInicio = null; // apertura de la venta: indicador «tiempo de registro»
    let ocupado = false;
    let codigoPendiente = null;

    function pesos(monto) {
        return "$" + Number(monto).toLocaleString("es-CL", { maximumFractionDigits: 0 });
    }

    function enfocar() {
        if (panelAlta.hidden) {
            campo.focus();
            campo.select();
        }
    }

    function mostrarAviso(tipo, texto) {
        aviso.replaceChildren();
        if (!texto) {
            return;
        }
        const caja = document.createElement("div");
        caja.className = "alert alert-" + tipo + " py-2 mb-0";
        caja.textContent = texto;
        aviso.appendChild(caja);
    }

    function limpiarConfirmacion() {
        panelDiferencias.hidden = true;
        confirmo.checked = false;
        errorVenta.hidden = true;
    }

    async function pedir(url, opciones) {
        const respuesta = await fetch(url, Object.assign({ credentials: "same-origin" }, opciones));
        let datos = {};
        try {
            datos = await respuesta.json();
        } catch (e) {
            datos = {};
        }
        return { estado: respuesta.status, datos: datos };
    }

    function postJSON(url, cuerpoJSON) {
        return pedir(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Accept: "application/json",
                "X-CSRFToken": csrf,
            },
            body: JSON.stringify(cuerpoJSON),
        });
    }

    // ---- Detalle de la venta -------------------------------------------------

    function recalcular() {
        let total = 0;
        lineas.forEach(function (linea) {
            const subtotal = linea.cantidad * linea.producto.precio;
            total += subtotal;
            linea.fila.querySelector('[data-campo="cantidad"]').value = linea.cantidad;
            linea.fila.querySelector('[data-campo="subtotal"]').textContent = pesos(subtotal);
            const avisoStock = linea.fila.querySelector('[data-campo="aviso-stock"]');
            const falta = !linea.altaRapida && linea.cantidad > linea.producto.stock_actual;
            avisoStock.hidden = !falta;
            avisoStock.textContent = "En el sistema hay " + linea.producto.stock_actual;
        });
        totalVista.textContent = pesos(total);
        sinLineas.hidden = lineas.size > 0;
        botonCobrar.disabled = lineas.size === 0;
    }

    function cambiarCantidad(id, nueva) {
        const linea = lineas.get(id);
        if (!linea) {
            return;
        }
        linea.cantidad = Math.min(9999, Math.max(1, nueva || 1));
        limpiarConfirmacion();
        recalcular();
    }

    function agregar(producto, altaRapida) {
        if (!horaInicio) {
            horaInicio = new Date().toISOString();
        }
        limpiarConfirmacion();
        const existente = lineas.get(producto.id_producto);
        if (existente) {
            existente.cantidad += 1;
            recalcular();
            return;
        }
        const fila = document.getElementById("plantilla-linea").content.firstElementChild.cloneNode(true);
        fila.querySelector('[data-campo="nombre"]').textContent = producto.nombre;
        fila.querySelector('[data-campo="precio"]').textContent = pesos(producto.precio);
        fila.querySelector('[data-campo="aviso-nuevo"]').hidden = !altaRapida;
        const id = producto.id_producto;
        fila.querySelector('[data-accion="mas"]').addEventListener("click", function () {
            cambiarCantidad(id, lineas.get(id).cantidad + 1);
            enfocar();
        });
        fila.querySelector('[data-accion="menos"]').addEventListener("click", function () {
            cambiarCantidad(id, lineas.get(id).cantidad - 1);
            enfocar();
        });
        fila.querySelector('[data-campo="cantidad"]').addEventListener("change", function (e) {
            cambiarCantidad(id, parseInt(e.target.value, 10));
        });
        fila.querySelector('[data-accion="quitar"]').addEventListener("click", function () {
            lineas.delete(id);
            fila.remove();
            limpiarConfirmacion();
            recalcular();
            enfocar();
        });
        lineas.set(id, { producto: producto, cantidad: 1, altaRapida: altaRapida, fila: fila });
        cuerpo.appendChild(fila);
        recalcular();
    }

    function vaciar() {
        lineas.forEach(function (linea) {
            linea.fila.remove();
        });
        lineas.clear();
        horaInicio = null;
        cerrarAlta();
        limpiarConfirmacion();
        mostrarAviso();
        recalcular();
        enfocar();
    }

    // ---- Escaneo y alta rápida (CU-02 2a) -----------------------------------

    function abrirAlta(codigo) {
        codigoPendiente = codigo;
        panelAlta.querySelector('[data-campo="codigo"]').textContent = codigo;
        formularioAlta.reset();
        formularioAlta.querySelector('[data-campo="error"]').hidden = true;
        panelAlta.hidden = false;
        document.getElementById("alta-nombre").focus();
    }

    function cerrarAlta() {
        panelAlta.hidden = true;
        codigoPendiente = null;
    }

    async function escanear(codigo) {
        if (ocupado) {
            return;
        }
        ocupado = true;
        try {
            const r = await pedir(raiz.dataset.urlBuscar.replace("CODIGO", encodeURIComponent(codigo)), {
                headers: { Accept: "application/json" },
            });
            if (r.estado === 200) {
                mostrarAviso();
                cerrarAlta();
                agregar(r.datos.producto, false);
            } else if (r.estado === 404) {
                mostrarAviso();
                abrirAlta(codigo);
            } else {
                mostrarAviso("danger", "No se pudo buscar el producto. Intenta de nuevo.");
            }
        } catch (e) {
            mostrarAviso("danger", "No hay conexión con el sistema. Revisa internet e intenta de nuevo.");
        } finally {
            ocupado = false;
            enfocar();
        }
    }

    formularioAlta.addEventListener("submit", async function (evento) {
        evento.preventDefault();
        const error = formularioAlta.querySelector('[data-campo="error"]');
        const nombre = document.getElementById("alta-nombre").value.trim();
        const precio = parseInt(document.getElementById("alta-precio").value, 10);
        if (!nombre || !Number.isInteger(precio) || precio < 0) {
            error.textContent = "Escribe el nombre y el precio de venta.";
            error.hidden = false;
            return;
        }
        const boton = formularioAlta.querySelector("button[type=submit]");
        boton.disabled = true;
        try {
            const r = await postJSON(raiz.dataset.urlAltaRapida, {
                codigo_barras: codigoPendiente,
                nombre: nombre,
                precio: precio,
            });
            if (r.estado === 201) {
                cerrarAlta();
                agregar(r.datos.producto, true);
                mostrarAviso("success", "«" + nombre + "» registrado y agregado a la venta.");
            } else if (r.estado === 409) {
                // Alguien lo registró recién: se usa el existente.
                cerrarAlta();
                agregar(r.datos.producto, false);
                mostrarAviso("info", "Ese código ya estaba registrado como «" + r.datos.producto.nombre + "».");
            } else {
                error.textContent = r.datos.detalle || "No se pudo registrar el producto.";
                error.hidden = false;
            }
        } catch (e) {
            error.textContent = "No hay conexión con el sistema. El producto no se registró.";
            error.hidden = false;
        } finally {
            boton.disabled = false;
            enfocar();
        }
    });

    panelAlta.querySelector('[data-accion="cancelar-alta"]').addEventListener("click", function () {
        cerrarAlta();
        enfocar();
    });

    // ---- Cobro (transacción única en el servidor) ----------------------------

    function mostrarDiferencias(diferencias) {
        const lista = panelDiferencias.querySelector('[data-campo="lista"]');
        lista.replaceChildren();
        diferencias.forEach(function (d) {
            const item = document.createElement("li");
            item.textContent = d.mensaje;
            lista.appendChild(item);
        });
        confirmo.checked = false;
        panelDiferencias.hidden = false;
        botonCobrar.textContent = "Registrar la venta igual";
        botonCobrar.disabled = true;
        confirmo.focus();
    }

    confirmo.addEventListener("change", function () {
        botonCobrar.disabled = !confirmo.checked;
    });

    async function cobrar() {
        if (ocupado || lineas.size === 0) {
            return;
        }
        ocupado = true;
        botonCobrar.disabled = true;
        errorVenta.hidden = true;
        const medio = document.querySelector("input[name=medio_pago]:checked");
        const cuerpoVenta = {
            lineas: Array.from(lineas.values()).map(function (l) {
                return { id_producto: l.producto.id_producto, cantidad: l.cantidad, alta_rapida: l.altaRapida };
            }),
            medio_pago: medio ? medio.value : "",
            hora_inicio: horaInicio,
            confirmar_diferencias: !panelDiferencias.hidden && confirmo.checked,
        };
        try {
            const r = await postJSON(raiz.dataset.urlVenta, cuerpoVenta);
            if (r.estado === 201) {
                window.location.assign(r.datos.url_comprobante + "?nueva=1");
                return;
            }
            if (r.estado === 409 && r.datos.requiere_confirmacion) {
                mostrarDiferencias(r.datos.diferencias);
            } else {
                errorVenta.textContent = r.datos.detalle || "No se pudo registrar la venta. No se descontó stock.";
                errorVenta.hidden = false;
                botonCobrar.disabled = false;
            }
        } catch (e) {
            errorVenta.textContent = "No hay conexión con el sistema. La venta NO se registró; intenta de nuevo.";
            errorVenta.hidden = false;
            botonCobrar.disabled = false;
        } finally {
            ocupado = false;
        }
    }

    botonCobrar.addEventListener("click", cobrar);
    botonVaciar.addEventListener("click", vaciar);

    campo.addEventListener("keydown", function (evento) {
        if (evento.key !== "Enter") {
            return;
        }
        evento.preventDefault();
        const codigo = campo.value.trim();
        campo.value = "";
        if (codigo) {
            escanear(codigo);
        }
    });

    // Un clic fuera de los controles devuelve el foco al campo de escaneo.
    document.addEventListener("click", function (evento) {
        if (!evento.target.closest("input, button, a, select, textarea, label")) {
            enfocar();
        }
    });

    // Al volver a la caja después de cambiar cantidades a mano, el texto del botón vuelve.
    new MutationObserver(function () {
        if (panelDiferencias.hidden) {
            botonCobrar.textContent = "Cobrar";
        }
    }).observe(panelDiferencias, { attributes: true, attributeFilter: ["hidden"] });

    recalcular();
    enfocar();
})();
