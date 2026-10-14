class ReglaDeNegocioError(Exception):
    """
    Una regla de negocio impidió la operación. El mensaje está escrito para el
    almacenero (se muestra tal cual en la interfaz), no para el desarrollador.
    """
