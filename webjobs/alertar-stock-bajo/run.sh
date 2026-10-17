#!/bin/bash
# Va en el mismo zip que webjob.sh (scripts/publicar_webjobs.py).
exec bash "$(dirname "$0")/webjob.sh" alertar_stock_bajo
