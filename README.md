# Render LLM Queue

API mínima para usar Render como cola pública y un worker local que llama a tu LLM.

## Deploy en Render

1. Sube estos archivos a GitHub.
2. En Render, crea un **New Web Service** desde ese repo.
3. Build command:
   ```bash
   pip install -r requirements.txt
   ```
4. Start command:
   ```bash
   gunicorn app:app --bind 0.0.0.0:$PORT
   ```
5. Añade una variable de entorno:
   ```txt
   API_TOKEN=un_token_largo_y_secreto
   ```

## Crear un trabajo

```bash
curl -X POST https://TU-APP.onrender.com/jobs \
  -H "Authorization: Bearer TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Hola, prueba"}'
```

## Consultar resultado

```bash
curl https://TU-APP.onrender.com/jobs/JOB_ID \
  -H "Authorization: Bearer TU_TOKEN"
```

## Worker local

```bash
set RENDER_URL=https://TU-APP.onrender.com
set API_TOKEN=TU_TOKEN
python worker_local.py
```

Edita `procesar_con_tu_llm()` para llamar a tu Flask local.
