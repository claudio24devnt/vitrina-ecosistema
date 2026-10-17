#!/bin/bash
# Ejecuta un comando de manage.py desde un WebJob de App Service Linux (1.6).
# Lo llaman los run.sh de App_Data/jobs/triggered/*. El WebJob corre en el mismo
# contenedor que la aplicación, con sus variables de entorno.
set -euo pipefail

# Oryx deja la aplicación y su entorno virtual (antenv) en /home/site/wwwroot, o,
# si comprimió la salida de la compilación, extraída en /tmp/<id>/. Se usa la
# primera ubicación que tenga ambas cosas.
# TIVOSCANEA_RAICES sólo para pruebas (tivoscanea/test_webjobs.py).
for dir in ${TIVOSCANEA_RAICES:-/home/site/wwwroot /tmp/*/}; do
    dir="${dir%/}"
    if [ -f "$dir/manage.py" ] && [ -f "$dir/antenv/bin/activate" ]; then
        cd "$dir"
        # shellcheck disable=SC1091
        source antenv/bin/activate
        echo "TivoScanea: python manage.py $* (en $dir)"
        exec python manage.py "$@"
    fi
done

echo "TivoScanea: no se encontró manage.py con su entorno antenv" >&2
exit 1
