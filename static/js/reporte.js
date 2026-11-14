// Reporte mensual: al pasar el cursor, tocar o llegar con el teclado a un día del
// gráfico, muestra lo vendido. Sin este archivo el detalle sigue en la tabla por día.
document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((elemento) => {
    new bootstrap.Tooltip(elemento, { container: "body" });
});
