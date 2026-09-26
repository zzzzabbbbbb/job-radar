# Job Radar

Radar diario de vacantes: lee los boards públicos de Greenhouse y Lever, descarta con reglas lo que claramente no aplica, puntúa lo que queda con Claude y manda un digest por correo con 0 a 10 vacantes. Corre en GitHub Actions, sin tu laptop.

El requerimiento original está en [`docs/job_radar_spec.md`](docs/job_radar_spec.md). Las decisiones abiertas de la sección 5 y lo que cambié respecto a la propuesta están en [`docs/PROPUESTA.md`](docs/PROPUESTA.md).

## Cómo funciona

```
companies.yaml ──► adaptador ATS ──► ¿ya la conocía? ──sí──► last_seen
   (30 boards)     (1 req/s, UA)           │no
                                           ▼
                                   prefiltro de reglas ──descarta──► SQLite con la razón
                                           │pasa (<10%)
                                           ▼
                                   dedup empresa+título ──duplicada──► SQLite
                                           │
                                           ▼
                                   Claude (perfil + reglas) ──► score ≥ 65 ──► digest
```

- **Fallas aisladas.** Si un board falla, el resto sigue, y la falla aparece en el digest. Un board que falló nunca marca vacantes como cerradas.
- **Nada se tira.** Lo descartado queda en la base con su razón. `python -m radar discards` lo agrupa para calibrar.
- **Sin repetir.** Cada vacante se puntúa y se notifica una sola vez. Si vuelve a aparecer con otro id pero con la misma empresa y el mismo título normalizado, se marca como duplicada.
- **Cerradas.** Si una vacante que salió en un digest (o que marcaste `applied`/`interviewing`) desaparece del board, el siguiente digest te avisa.
- **Costo acotado.** Máximo 30 puntuaciones por corrida y tope mensual de $4.50 (`config/settings.yaml`). Si se alcanza, deja de puntuar y el digest lo avisa.

## Puesta en marcha

1. **Repo privado.** La base incluye tu perfil y tu historial de postulaciones.
2. **Rama por defecto.** Los `schedule` de Actions solo corren en la rama por defecto: haz merge de este trabajo a `main`.
3. **Secrets** (Settings → Secrets and variables → Actions):

   | Secret | Valor |
   |---|---|
   | `ANTHROPIC_API_KEY` | tu llave de la API de Claude |
   | `SMTP_HOST` | `smtp.gmail.com` |
   | `SMTP_PORT` | `465` |
   | `SMTP_USER` | la cuenta que envía (sugerencia: la misma cuenta dedicada que usarás para las alertas del canal B) |
   | `SMTP_PASSWORD` | una [contraseña de aplicación](https://myaccount.google.com/apppasswords) de esa cuenta, no la contraseña normal |
   | `DIGEST_TO` | tu correo |

4. **Verifica la lista de empresas.** Actions → *probe ATS* → Run, marcando *verificar companies.yaml*. Los boards que no respondan se corrigen con el mismo workflow (pon el nombre de la empresa y te da la línea lista para pegar).
5. **Calibra el scorer.** Actions → *calibrate scorer*. Tiene que dar 6/6 antes de confiar en el digest. Los casos están en `calibration/cases.yaml`; reemplázalos por vacantes que tú hayas evaluado.
6. **Primera corrida.** Actions → *daily radar* → Run. Si quieres ver primero qué pasa el prefiltro sin gastar, marca *no_llm*. A partir de ahí corre solo todos los días a las 7:07 (CDMX).

## Operación diaria

| Quiero... | Cómo |
|---|---|
| Agregar una empresa | Una línea en `config/companies.yaml`. Si no sabes el token: workflow *probe ATS* o `python -m radar probe "Nombre"` |
| Ver qué se descartó esta semana | `python -m radar discards --days 7 -v` |
| Marcar que apliqué | `python -m radar status <url-de-la-vacante> applied` y commit de `data/radar.sql` |
| Ajustar reglas o umbrales | `config/settings.yaml` |
| Cambiar el perfil | `config/profile.yaml` y vuelve a correr la calibración |
| Ver digests anteriores | carpeta `digests/` en el repo, o el resumen de cada corrida en Actions |

## Local

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q                        # pruebas con fixtures, sin red
python -m radar run --no-llm --no-email    # corrida real sin gastar ni mandar correo
```

El estado vive en `data/radar.sql`, un dump de texto que se commitea después de cada corrida, porque git guarda los diffs de texto mucho mejor que un binario que cambia diario. `data/radar.db` se reconstruye solo a partir de él.

## Estructura

```
config/          perfil, reglas del prefiltro y umbrales, lista de empresas
calibration/     set de 6 vacantes para validar el scorer
radar/sources/   un adaptador por ATS (greenhouse.py, lever.py)
radar/prefilter.py   etapa 1, reglas
radar/scorer.py      etapa 2, Claude con salida JSON estructurada
radar/pipeline.py    la corrida diaria
radar/digest.py      el markdown del correo
.github/workflows/   daily, probe, calibrate, tests
```
