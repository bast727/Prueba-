# Monitor de notas UCSC

Revisa cada 30 minutos la página de notas del Portal UCSC y manda una notificación al celular (app **ntfy**) cuando cambia.

## Configuración (una sola vez)

1. **Instala ntfy** en el celular (App Store / Play Store). Toca "+" y suscríbete a un canal con un nombre largo e inventado, por ejemplo `notas-bastian-x7k29qpl`. Cualquiera que sepa el nombre puede leerlo, así que no uses algo obvio.
2. En GitHub: **Settings → Secrets and variables → Actions → New repository secret**, crea:
   - `UCSC_RUT`: tu RUT sin puntos ni dígito verificador
   - `UCSC_PASSWORD`: tu contraseña del portal
   - `NTFY_TOPIC`: el nombre del canal del paso 1
3. Pestaña **Actions → Monitor de notas UCSC → Run workflow** para probarlo. La primera vez llega el aviso "Monitor de notas activo".

## Opcional (pestaña *Variables*, no *Secrets*)

- `NTFY_DETALLE` = `1`: la notificación incluye las líneas nuevas (p. ej. "Nota 2: 6.1"). Sin esto solo dice que hubo un cambio.
- `NOTAS_SELECTOR`: selector CSS para leer solo la tabla de notas, si llegan avisos por cambios que no son notas.

## Seguridad

- El repo es público: el script nunca imprime tus notas en los registros, y solo guarda huellas (hashes), no las notas.
- Si el portal rechaza el inicio de sesión, el monitor te avisa y **se desactiva solo** para no bloquear tu cuenta (el portal bloquea tras 6 intentos fallidos). Corrige el secret y reactívalo en Actions → "Enable workflow".
- GitHub pausa las tareas programadas de repos sin actividad por 60 días; si pasa, reactívalo en Actions.
