/*
 * Evita enviar dos veces un formulario (POST) mientras el servidor responde.
 * Guardar una contraseña tarda varios segundos en el plan B1: sin esto, un segundo
 * toque llegaba cuando el enlace de recuperación ya se había usado y mostraba
 * «Este enlace ya no sirve» aunque la contraseña sí se había cambiado.
 *
 * Los botones no se deshabilitan (un botón deshabilitado no envía su name/value):
 * se ignoran los envíos repetidos y el botón muestra «Procesando…».
 * Los formularios que maneja su propio JavaScript (la caja) llaman a
 * preventDefault() y aquí no se tocan.
 */
(function () {
    "use strict";

    document.addEventListener("submit", function (evento) {
        const formulario = evento.target;
        if (evento.defaultPrevented || (formulario.method || "").toLowerCase() !== "post") {
            return;
        }
        if (formulario.dataset.enviando) {
            evento.preventDefault();
            return;
        }
        formulario.dataset.enviando = "1";
        const boton = evento.submitter;
        if (boton && boton.tagName === "BUTTON") {
            boton.dataset.textoOriginal = boton.textContent;
            boton.textContent = "Procesando…";
            boton.classList.add("disabled");
            boton.setAttribute("aria-disabled", "true");
        }
    });

    // Al volver con «Atrás», el navegador puede restaurar la página tal como quedó.
    window.addEventListener("pageshow", function () {
        document.querySelectorAll("form[data-enviando]").forEach(function (formulario) {
            delete formulario.dataset.enviando;
        });
        document.querySelectorAll("button[data-texto-original]").forEach(function (boton) {
            boton.textContent = boton.dataset.textoOriginal;
            delete boton.dataset.textoOriginal;
            boton.classList.remove("disabled");
            boton.removeAttribute("aria-disabled");
        });
    });
})();
