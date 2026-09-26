# Propuesta: respuestas a la sección 5 y decisiones de la v1

Fecha: 2026-09-26. Lo que está aquí es criterio y está pensado para discutirse. Lo que ya está construido es la v1 de la sección 7 y no contradice nada de esto.

## Resumen

| # | Pregunta | Respuesta corta |
|---|---|---|
| 1 | ¿Agregador legítimo? | Sí: **Get on Board** (API pública, LatAm, incluye México). Secundario: Himalayas. No reemplazan al canal B, pero cubren la falla 1 mejor que él. |
| 2 | ¿Detectar el ATS automáticamente? | Sí por nombre de empresa (ya está: `radar probe`). Por dominio no vale la pena. Workday no se puede adivinar. |
| 3 | ¿Cómo poblar la lista sin depender de lo que conozco? | **Buscar al revés: en los dominios de los ATS por rol y ubicación.** Así armé la lista semilla. Propongo automatizarlo semanalmente. |
| 4 | ¿Reglas o modelo chico? | Reglas. Un modelo chico sobre todo lo nuevo se come el presupuesto entero. |
| 5 | ¿Dashboard? | No. La carpeta `digests/` en el repo ya da el historial. GitHub Pages en repo privado requiere plan de pago. |
| 6 | ¿Qué sobra? | El canal B por IMAP es la pieza más frágil del diseño. Lo pondría después de Get on Board, y solo si hace falta. `tier` hoy no hace nada. |

---

## 1. Agregadores legítimos

**Get on Board** ([getonbrd.com](https://www.getonbrd.com/)) es el board de empleos tech más grande de LatAm, con vacantes en México, remoto LatAm y salarios publicados. Tiene [API pública documentada](https://www.getonbrd.com/help/what-can-i-do-with-get-on-board-s-api): sin llave y sin registro, con los mismos datos que se ven en el sitio sin iniciar sesión, e incluye búsqueda por texto. Es exactamente el tipo de fuente que pide la pregunta. Además, muchas empresas que publican ahí no tienen board en Greenhouse o Lever, así que ataca directamente la falla 1.

**Himalayas** ([himalayas.app/api](https://himalayas.app/api)) tiene JSON público y sin auth para vacantes remotas. Hay que dar crédito y enlazar a la fuente, y está prohibido redistribuir, lo cual no aplica a un uso personal. Tiene un tope de 20 vacantes por petición, así que conviene usar su búsqueda y no paginar todo.

**Remotive** también tiene API pública, pero es mayormente remoto global y se traslapa con Himalayas.

**Qué no hacen:** no ven lo que solo existe en LinkedIn, Indeed u OCC. Ese es el hueco que el canal B sigue cubriendo. Pero por costo y fragilidad, Get on Board rinde más que el canal B, así que propongo hacerlo primero en la v2.

Desde este entorno no pude verificar los esquemas en vivo, porque la red del contenedor bloquea esos dominios. El adaptador se escribiría y se probaría con el workflow *probe* en Actions, que sí tiene red.

## 2. Detección automática de ATS

Hay dos versiones de la pregunta:

- **Por nombre de empresa:** funciona y ya está construida (`python -m radar probe "Nombre"` o el workflow *probe ATS*). Prueba variantes del slug (`grafanalabs`, `grafana-labs`, `grafana`...) contra Greenhouse, Lever, Ashby y SmartRecruiters, y devuelve la línea lista para `companies.yaml`. Los slugs de Greenhouse, Lever y Ashby casi siempre son el nombre de la empresa, así que la tasa de acierto debería ser alta. Esto lo adelanté de la v3 porque sin red aquí era la única forma de que validaras la lista semilla en un minuto.
- **Por dominio** (abrir `empresa.com/careers` y seguir redirecciones): requiere un navegador headless, porque las páginas se renderizan con JS. Es justo el mantenimiento que quieres evitar. No lo haría.
- **Workday:** el endpoint necesita tenant, número de data center (`wd1`, `wd5`...) y nombre del sitio. No se adivina; se copia una vez de la URL. Sigue siendo una línea de config, pero manual.

## 3. Poblar la lista de empresas (la falla que más importa)

Las listas tipo YC Top Companies o Forbes Cloud 100 tienen dos problemas: están sesgadas a empresas de EE. UU. y a empresas famosas. Es decir, a las que ya conoces. Apollo no habría salido ahí.

**Lo que funcionó para armar la semilla:** buscar al revés. Los boards de los ATS son páginas públicas indexadas, así que una búsqueda como `site:jobs.lever.co "Mexico City" support engineer` devuelve directamente empresas que hoy contratan tu perfil en CDMX. De ahí salieron JumpCloud, PayJoy, Deliverect, Restaurant365, Coupa, Wing Assistant, Varicent, Tenable, EarnIn, Fictiv y DYOPATH. La mayoría no son nombres que uno buscaría por su cuenta, que es justo el punto.

**Propuesta para automatizarlo (v2):** un job semanal que:

1. Corre unas 10 búsquedas fijas del tipo (rol × ubicación × dominio de ATS) con la herramienta de web search de la API de Claude. Son centavos por semana.
2. Extrae los tokens de las URLs (`job-boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`, `jobs.ashbyhq.com/<token>`).
3. Descarta los que ya están en `companies.yaml` y valida el resto con `probe`.
4. Los lista en el digest del lunes: "Empresas nuevas que contratan tu perfil: X, Y, Z". Tú decides si entran; es una línea cada una.

Fuentes complementarias:

- **Get on Board:** su API expone las empresas que publican.
- **El ecosistema de las herramientas que ya usas:** Okta, Kandji, Tray.io, Splunk, AppDynamics, Grafana. Su lista de clientes y partners es una lista de empresas con stack parecido al tuyo.

## 4. Prefiltro: reglas o modelo chico

Reglas, por números. Treinta boards pueden traer 50 a 150 vacantes nuevas al día. Un modelo chico (Haiku 4.5, $1/M de entrada) sobre cada una, con unos 2,000 tokens por vacante, cuesta alrededor de $0.10 a $0.30 al día, es decir $3 a $9 al mes solo en el prefiltro. Eso se come el presupuesto antes de puntuar nada.

Las reglas son gratis, deterministas, y cada descarte dice exactamente por qué. Eso es lo que hace útil la revisión semanal. El riesgo, que es tirar cosas buenas, se mitiga con dos cosas:

- Las reglas son conservadoras donde hay ambigüedad. "Mexico" a secas, remoto sin país o ubicación vacía pasan al LLM.
- `radar discards` agrupa lo descartado por razón.

Si la revisión semanal muestra un patrón que las reglas no pueden capturar, se agrega una regla, no un modelo.

## 5. Dashboard

No por ahora. Lo que la v1 ya da gratis:

- `digests/AAAA-MM-DD.md` commiteado cada día. GitHub lo renderiza, y es tu historial navegable.
- El resumen de cada corrida en la pestaña Actions.
- `data/radar.sql`, consultable con cualquier cliente SQLite.

GitHub Pages en un repo privado requiere GitHub Pro. En uno público expondría tu búsqueda de trabajo. Las métricas de la v3 (cuánto duran abiertas las vacantes por empresa) caben en una sección semanal del digest sin infraestructura nueva.

## 6. Lo que está sobrediseñado o es frágil

- **Canal B (IMAP + alertas).** Parsear los correos de alertas de LinkedIn, Indeed y OCC *es* mantener parsers de HTML: esos correos cambian de formato sin aviso. Es la pieza que más va a romperse. Sugerencia: suscribir las alertas desde ya a la cuenta dedicada (eso no cuesta nada) y decidir en la v2, con datos, si vale la pena parsearlas o basta con leerlas. Si se hace, que el parser solo extraiga el link y el título y le deje el resto al scorer.
- **`tier`.** Hoy es informativo. Podría servir para ordenar empates o para bajar el umbral en tier 1, pero no lo usaría hasta ver si hace falta.
- **Commitear el SQLite binario.** Ya está resuelto: se commitea un dump de texto (`data/radar.sql`).
- **Dedup por título normalizado entre canales.** Es barato y ya está; se queda.

---

## Decisiones de la v1 que debes revisar

### Modelo del scorer y costo (esto es decisión tuya)

La v1 viene con **Claude Opus 5** con effort `low`. Es el más capaz de los tres, y el modo de falla principal es un scorer demasiado generoso. Costo estimado por vacante puntuada, con el perfil cacheado:

| Modelo | ~USD por vacante | 5 vacantes/día | 10 vacantes/día |
|---|---|---|---|
| Claude Opus 5 | ~$0.03 | ~$4.50/mes | ~$9/mes |
| Claude Sonnet 5 | ~$0.012 | ~$1.80/mes | ~$3.60/mes |
| Claude Haiku 4.5 | ~$0.006 | ~$0.90/mes | ~$1.80/mes |

Son estimaciones. El costo real queda registrado por vacante en la base y el digest muestra el acumulado del mes.

La restricción de menos de $5 al mes la garantiza el tope en `settings.yaml` (`monthly_budget_usd: 4.50`): al llegar ahí deja de puntuar y lo avisa. Si con Opus 5 el volumen tras el prefiltro pasa de unas 5 vacantes al día, se alcanzará el tope a mitad de mes.

Mi sugerencia: corre la calibración con los tres modelos (el workflow deja elegir). Si Sonnet 5 o Haiku 4.5 sacan 6/6, cambia `scorer.model` a ese. La calibración es la que decide, no el precio de lista.

Con Opus 5 está activado el *fallback* del servidor: si el modelo rechazara una vacante por política, otro modelo la puntúa en la misma llamada. Es muy improbable en este uso, pero evita perder una vacante por eso.

### Otras decisiones

- **Senior en el título se descarta** (`discard_senior: true`). Con 3.5 años, la mayoría de los "Senior" piden 5 o más. Es el ajuste más probable si en la revisión semanal ves seniors que sí te interesaban.
- **Vacantes con más de 30 días al verlas por primera vez se descartan.** Evita que la primera corrida puntúe todo el backlog, y va con la falla 3.
- **"Incident Manager" pasa** aunque "manager" esté en la lista de seniority, porque es un rol de tu perfil.
- **El correo es markdown en texto plano**, como pide el requerimiento. Si prefieres HTML renderizado, es un cambio chico.
- **Palabras clave para el canal C:** fuera de la v1. Con dos semanas de vacantes puntuadas, el `matches` de las que sacan 65 o más da esa lista directamente; es una consulta, no una feature.

## Lo que falta para cerrar la v1

1. Configurar los secrets y hacer merge a la rama por defecto.
2. Correr *probe ATS* con `check_config` y corregir los tokens de las empresas `verified: false`.
3. Correr *calibrate scorer* hasta 6/6, idealmente con 6 vacantes que tú hayas evaluado.
4. Una semana de digests, y leerlos, antes de tocar la v2.
