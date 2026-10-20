# Monitor de notas UCSC

Cada 5 minutos entra al Portal UCSC, abre la "Ficha del curso" y busca el aviso **"(una nota nueva en los últimos 7 días)"** junto a cada ramo. Cuando aparece en un ramo nuevo, te llega una notificación al celular: *"Nueva nota en Optimización"*.

## Configuración (una sola vez)

1. **Instala ntfy** en el celular (App Store / Play Store). Toca "+" y suscríbete a un canal con un nombre largo e inventado, por ejemplo `notas-bastian-x7k29qpl`. Cualquiera que sepa el nombre puede leerlo, así que no uses algo obvio.
2. En GitHub: **Settings → Secrets and variables → Actions → New repository secret**, crea:
   - `UCSC_RUT`: tu RUT sin puntos ni dígito verificador
   - `UCSC_PASSWORD`: tu contraseña del portal
   - `NTFY_TOPIC`: el nombre del canal del paso 1
3. Pestaña **Actions → Monitor de notas UCSC → Run workflow** para probarlo. Llega el aviso "Monitor de notas activo" con los ramos que hoy tienen nota nueva.
4. **Recomendado:** instala la app de GitHub y activa sus notificaciones. Es el respaldo si ntfy falla.

### Opcional: cuenta gratis de ntfy (más confiable)
ntfy sin cuenta limita los mensajes por IP, y los servidores de GitHub se comparten con mucha gente. Crea una cuenta gratis en ntfy.sh, genera un *access token* (Account → Access tokens) y guárdalo como secret `NTFY_TOKEN`.

## Qué pasa si algo falla

- **ntfy no responde:** se abre un issue en el repo y la app de GitHub te manda un push. Si tampoco funciona, la nota no se marca como vista y se reintenta en 5 minutos.
- **Portal caído:** sigue intentando sin llenarte de correos de error. Si pasa ~1 hora sin poder leerlo, te avisa una vez.
- **Contraseña rechazada:** te avisa y **se desactiva solo** para no bloquear tu cuenta (el portal bloquea tras 6 intentos fallidos). Corrige el secret y reactívalo en Actions → "Enable workflow".
- GitHub pausa las tareas de repos sin actividad por 60 días; el monitor se mantiene activo solo.

## Privacidad

El repo es público: los registros nunca muestran ramos ni notas, y el issue de respaldo solo dice "Nueva nota en el portal UCSC".

## Límite

GitHub programa cada 5 minutos, pero en horas de mucho uso puede atrasarse unos minutos más.
