#!/bin/bash
# Va en el mismo zip que webjob.sh (scripts/publicar_webjobs.py).
exec bash "$(dirname "$0")/webjob.sh" avisar_cierre_mes
