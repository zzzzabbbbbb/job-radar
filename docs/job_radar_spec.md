# Job Radar — Requerimiento

> Este documento describe un objetivo, no una implementación cerrada. La sección 4 propone una arquitectura, pero si al investigar encuentras un camino más simple o más confiable, propónlo y explica por qué antes de construirlo. Lo único no negociable es la sección 3.

---

## 1. El objetivo

Soy ingeniero de IT y soporte de aplicaciones en Ciudad de México. Estoy buscando trabajo activamente y el proceso tiene tres fallas que quiero resolver con software.

**Falla 1. No me entero de empresas que no conozco.**

Trabajé en Apollo.io y fue el mejor trabajo que he tenido. Nunca había oído hablar de ellos. Jamás se me hubiera ocurrido buscar si tenían vacantes abiertas. Si mi búsqueda depende de las empresas que ya tengo en la cabeza, por definición nunca voy a encontrar la siguiente Apollo.

**Falla 2. El volumen hace inviable revisar a mano.**

Hay cientos de vacantes abiertas de observabilidad, application support, IT engineering, automatización y soporte técnico. La gran mayoría no me aplican, porque piden seis años, o experiencia experta en un lenguaje que no domino, o son presenciales en otro país. Filtrar eso manualmente todos los días no es sostenible.

**Falla 3. Me entero tarde.**

Encuentro vacantes publicadas hace tres semanas y llego al final de la fila. Revisar diario resuelve esto.

---

## 2. Cómo se ve el éxito

El sistema funciona si, después de dos semanas corriendo, se cumple todo esto.

- Cada mañana recibo un digest con entre cero y diez vacantes, no cincuenta. Si me manda cincuenta, el filtro está roto y lo voy a dejar de leer.
- De lo que aparece en el digest, al menos la mitad me parece razonable para aplicar. Si menos de la mitad lo son, el scoring es demasiado generoso.
- Aparece al menos una empresa que yo no conocía.
- No me repite una vacante que ya vi.
- Cuando una vacante que me interesaba desaparece del board, me entero.
- Cuando una fuente falla, me entero en el digest. No falla en silencio.

**Anti-objetivo explícito.** Este sistema no está para mostrarme todo lo que existe. Está para mostrarme lo poco que vale la pena. Un falso negativo cuesta menos que cincuenta falsos positivos, porque los falsos positivos hacen que deje de abrir el correo.

---

## 3. Restricciones no negociables

- **No scrapear LinkedIn, Indeed, Glassdoor ni OCC.** Bloquean activamente y va contra sus términos de servicio. Si necesitas datos de ahí, la vía es sus alertas por correo, que son gratis y están hechas para eso.
- **Costo operativo bajo.** Menos de cinco dólares al mes. Si el diseño implica puntuar cientos de vacantes diarias con un modelo grande, está mal diseñado.
- **Mantenimiento cercano a cero.** Agregar una empresa nueva debe costar minutos, no una tarde de escribir un scraper. Si la solución requiere mantener cincuenta parsers de HTML, no sirve.
- **Falla aislada.** Si una fuente se rompe, el resto de la corrida sigue y el digest lo reporta.
- **El perfil incluye mis límites reales.** El scoring tiene que poder decir que no. Un sistema que aprueba todo no me ahorra nada.
- **Corre sin mi laptop.** Tiene que funcionar aunque la computadora esté apagada.

---

## 4. Lo que yo intentaría primero

Esta es mi propuesta. Tómala como punto de partida informado, no como especificación cerrada.

### 4.1 Tres canales, no uno

Descubrí que un solo canal no basta. La vacante de Apollo nunca apareció en el board público de nadie. A mí me contactaron directo por Indeed. Entonces el sistema necesita cubrir tres rutas distintas.

**Canal A. Boards públicos, vía API de ATS.**

Casi todas las empresas de tecnología usan uno de cinco ATS, y su página de carreras es literalmente el board de ese ATS con su logo encima. Esos ATS exponen el board completo como JSON público, sin autenticación.

Esto importa porque leer esa API no es una estrategia distinta a "revisar su página de carreras". Es la misma cosa, por la puerta limpia. La alternativa, scrapear el HTML, requiere un navegador headless por empresa porque casi todas esas páginas se renderizan con JavaScript, y además rompe en silencio cuando cambian el diseño.

| ATS | Endpoint |
|---|---|
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` |
| Lever | `GET https://api.lever.co/v0/postings/{company}?mode=json` |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true` |
| SmartRecruiters | `GET https://api.smartrecruiters.com/v1/companies/{company}/postings` |
| Workday | `POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` |

Agregar una empresa es una línea de configuración.

```yaml
- name: Deel
  ats: greenhouse
  token: deel
  tier: 1
```

Para identificar el ATS de una empresa, se abre su página de carreras una sola vez y se ve a dónde redirige. Dos minutos por empresa, nunca se vuelve a tocar.

Para las pocas empresas con board propio de verdad, ahí sí un scraper dedicado, pero como excepción y no como regla.

**Canal B. Alertas de agregadores, leídas desde un buzón.**

Este canal existe porque una vacante puede estar viva en el ATS sin estar publicada en el board público. El ATS deja elegir dónde se lista. Esas vacantes solo aparecen en Indeed, LinkedIn u OCC.

En vez de scrapear esos sitios, me suscribo a sus alertas por correo con mis términos de búsqueda, dirigidas a una cuenta dedicada. El sistema lee ese buzón por IMAP, extrae los enlaces y los metadatos, y los mete al mismo prefiltro y al mismo scorer que el canal A.

Es gratis, es legal, es estable, y es el canal que hubiera cachado Apollo.

**Canal C. Ser encontrable.**

A mí no me encontró una vacante, me encontró un reclutador. Ningún scraper resuelve eso.

Esto no es código, es configuración de mis perfiles. Lo pongo aquí porque es parte del sistema aunque no sea parte del software, y porque probablemente sea el canal de mayor rendimiento de los tres.

Si el proyecto puede ayudar con algo aquí, es generando la lista de palabras clave que aparecen con más frecuencia en las vacantes que sí puntúan alto, para que yo las refleje en mi perfil.

### 4.2 Filtro en dos etapas

Puntuar todo con un LLM es caro y lento. Por eso primero un prefiltro determinista barato.

**Etapa 1, reglas.** Descarta por ubicación incompatible, por seniority fuera de rango en el título, por disciplina equivocada, por años exigidos que exceden mi perfil por más de dos, y por lenguajes exigidos como requisito duro que no tengo. Debe descartar más del 90%. Si descarta menos, está mal calibrado.

Todo lo descartado se guarda en la base con la razón. No se tira. Una vez por semana reviso qué se descartó para calibrar.

**Etapa 2, LLM.** Solo sobre lo que sobrevivió. Recibe mi perfil completo y la vacante, y devuelve JSON estructurado.

```json
{
  "fit_score": 0,
  "verdict": "apply_now | worth_considering | stretch | skip",
  "matches": [],
  "gaps": [],
  "blockers": [],
  "seniority_read": "below | at_level | above",
  "one_line": ""
}
```

Reglas que deben ir textuales en el prompt del scorer, porque el modo de falla más probable es que sea demasiado optimista.

- Sé escéptico, no generoso. La mayoría de las vacantes no encajan.
- Si hay un blocker duro del perfil, el score es menor a 30 aunque todo lo demás se vea bien.
- No infieras habilidades que el perfil no declara. Administrar Okta no es configurar SAML.
- La sección de límites del perfil pesa tanto como la de fortalezas.
- Un rol que pide el doble de años de los que tengo es un skip, no un stretch.
- Ante la duda, skip.

Solo entran al digest los de score 65 o más.

**Calibración obligatoria antes de considerarlo terminado.** Armar un set de prueba con seis vacantes reales, tres que claramente encajan y tres que claramente no, y verificar que el scorer las clasifica bien. Si no, ajustar el prompt antes de seguir.

### 4.3 Estado y deduplicación

SQLite, un archivo. Clave primaria compuesta por ats, empresa e id de la vacante.

Si ya existe, solo se actualiza `last_seen`. No se vuelve a puntuar ni a notificar.

Si una vacante estaba ayer y hoy no, se marca `closed_at`. Sirve para saber cuánto duran abiertas las vacantes de cada empresa.

Un campo `status` que yo actualizo a mano, con valores new, applied, interviewing, rejected, ignored. Eso convierte el radar en tracker de postulaciones también.

### 4.4 Ejecución y entrega

GitHub Actions con schedule diario, no cron local, porque tiene que correr con la laptop apagada. El SQLite se commitea al repo después de cada corrida, lo cual da historial gratis. Las llaves en GitHub Secrets.

Entrega por correo, en markdown, ordenado por score. Incluye al final qué fuentes fallaron y qué vacantes se cerraron desde ayer.

---

## 5. Dónde quiero tu criterio

Estas son decisiones abiertas. Investiga y propón antes de construir.

1. **¿Hay un agregador legítimo que me esté perdiendo?** Existen APIs y feeds públicos de empleo. Si alguno cubre bien el mercado mexicano o el remoto de LatAm con términos de uso que lo permitan, vale más que el canal B completo.

2. **¿Se puede detectar el ATS de una empresa automáticamente?** Dado un dominio, probar los endpoints con variantes del nombre y ver cuál responde. Si funciona con buena tasa de acierto, agregar empresas se vuelve trivial y la lista puede crecer a cientos.

3. **¿Cómo poblar la lista de empresas sin depender de lo que yo conozco?** Esta es la falla número uno del documento y la que más me importa. Ideas que se me ocurren, pero probablemente hay mejores. La lista de top companies de Y Combinator. Forbes Cloud 100. Los competidores y el ecosistema de las empresas que ya me gustan. Las empresas detrás de las herramientas que uso a diario. Si encuentras una fuente estructurada mejor, úsala.

4. **¿El prefiltro debería ser reglas o un modelo chico?** Propuse reglas por costo. Si un modelo pequeño y barato clasifica mejor por casi el mismo precio, prefiero eso.

5. **¿Vale la pena un dashboard?** Propuse digest por correo porque funciona sin infraestructura. Si un HTML estático regenerado en cada corrida y servido desde GitHub Pages aporta lo suficiente, hazlo.

6. **Cualquier cosa que esté sobrediseñando.** Si algo de la sección 4 es innecesario para cumplir la sección 2, dímelo y quítalo.

---

## 6. Mi perfil

Este archivo es el que hace que el scoring sea honesto. Los límites son tan importantes como las fortalezas.

```yaml
titles_of_interest:
  - IT Engineer
  - IT Specialist
  - Application Support Analyst / Engineer
  - Incident Response / Incident Commander
  - Site Reliability Engineer (junior a mid)
  - Observability Engineer
  - Automation Engineer / Automation Specialist
  - Technical Support Engineer
  - Customer Support Engineer

years_experience:
  it_and_support: 3.5
  engineering_building: 1

strengths:
  - Respuesta a incidentes en producción, triage, coordinación de war rooms
  - Observabilidad con Splunk, AppDynamics, Grafana
  - Administración de Okta SSO, provisioning, MFA
  - Kandji MDM y gestión de flota macOS
  - Automatización de workflows con Tray.io, REST APIs, webhooks
  - Administración de Google Workspace en múltiples dominios
  - Soporte técnico a clientes bajo SLA, incluyendo cuentas enterprise
  - Gestión de cambios, documentación, runbooks

honest_limits:
  - La experiencia en identidad es operativa, no de configuración. Nunca he configurado SAML ni SCIM desde cero.
  - Nunca he usado Apple Business Manager.
  - El código que escribo es asistido por IA. Puedo leer, modificar y desplegar, pero no soy ingeniero de software puro.
  - Sin profundidad práctica en Datadog ni Prometheus.
  - Sin Fortinet, sin certificaciones de Cisco.
  - Sin profundidad en SQL ni data warehouse.
  - Sin Kubernetes, sin Terraform.
  - Sin MDM de Windows. Mi experiencia de MDM es macOS.

hard_blockers:
  - Pide 5 años o más de experiencia en ingeniería
  - Pide nivel experto en un lenguaje que no tengo (Ruby, Go, C, C++, Java, Scala)
  - Requiere security clearance
  - Presencial fuera de Ciudad de México, o requiere reubicación
  - Exige título en Ciencias de la Computación como filtro duro

constraints:
  location: Ciudad de México
  remote_ok: true
  hybrid_cdmx_ok: true
  onsite_cdmx_ok: true
  onsite_elsewhere: false
  min_monthly_mxn: 50000
  languages: [inglés fluido, español nativo]

positive_signals:
  - okta, sso, saml, scim, identity, iam
  - mdm, kandji, jamf, intune, macos, apple
  - incident, on-call, sre, observability, mttr, runbook
  - splunk, datadog, grafana, appdynamics, prometheus
  - itsm, servicenow, jira, zendesk, itil
  - automation, integration, api, webhook, zapier, tray.io, workflow
  - technical support, customer support engineer, application support
```

---

## 7. Fases

**v1.** Greenhouse y Lever. Treinta empresas. Prefiltro, scorer, SQLite, digest por correo, GitHub Action. Calibración del scorer con el set de seis vacantes. Con eso ya sirve.

**v2.** Ashby y SmartRecruiters. Canal B, el buzón de alertas. Subir a ochenta empresas. Campo status para trackear postulaciones.

**v3.** Workday. Detección automática de ATS por dominio. Dashboard. Métricas de cuánto duran abiertas las vacantes por empresa.

No construyas v2 antes de que v1 haya corrido una semana completa y yo haya leído los digests.

---

## 8. Modos de falla conocidos

**El scorer es demasiado generoso.** El más probable. Mitigación, los límites en el perfil, las reglas explícitas en el prompt, y la calibración obligatoria.

**El prefiltro descarta cosas buenas.** Por eso todo lo descartado se guarda con su razón, para poder revisarlo.

**Una fuente cambia su API.** Cada adaptador falla aislado. El digest reporta cuáles fallaron.

**El digest crece y lo dejo de leer.** Si un día trae más de quince vacantes, el sistema debe avisar que los umbrales necesitan ajuste.

**Rate limiting.** Un segundo entre peticiones, User-Agent identificable. Son endpoints públicos pero no hay que abusar.

**Duplicados.** La misma vacante puede aparecer en el board global y en uno regional, o llegar por canal A y canal B a la vez. Deduplicar por empresa más título normalizado, además de por id.
