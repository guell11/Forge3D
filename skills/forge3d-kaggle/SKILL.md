---
name: forge3d-kaggle
description: Conectar um agente ao Forge3D hospedado em Kaggle via API HTTPS autenticada e gerar modelos 3D.
---

# Forge3D no Kaggle

Use a URL HTTPS mostrada no fim do notebook Kaggle como origem da API. Nunca inclua `/api` no valor de `FORGE3D_API_URL`.

Peça ao usuário a URL HTTPS e acesso ao token de forma segura. Não imprima, grave em repositório nem envie tokens em mensagens públicas. Configure no ambiente protegido do cliente MCP:

```text
FORGE3D_API_URL=https://SEU-ENDERECO.ngrok-free.app
FORGE3D_API_TOKEN=<mesmo FORGE3D_ACCESS_TOKEN da sessão Kaggle>
```

Instale a bridge MCP do checkout Forge3D com `backend/requirements-mcp.txt` e execute `python -m app.mcp_server` com o diretório de trabalho `backend` (veja `docs/MCP.md` para a configuração do cliente). A bridge envia o Bearer token ao gateway do Kaggle.

## Fluxo de trabalho

1. Chame `describe_api`, depois `capabilities`; confirme se há geração disponível.
2. Chame `upload_image(path)` com PNG, JPEG, WEBP ou BMP local e obtenha `upload.id`.
3. Chame `generate_model(upload_id, adapter="auto", output_format="glb", options={"faithc":"off"})`.
4. Acompanhe o ID retornado com `wait_job(job_id, timeout_seconds=20)` ou `get_job(job_id)`. Timeout de espera não significa falha.
5. Após status `completed`, use `download_model(job_id, destination)` em um caminho local novo.

Não repita criação de job após timeout de rede sem consultar `list_jobs` e `get_job`, pois o servidor pode já ter recebido a solicitação. O Kaggle precisa continuar executando para a API funcionar. Consulte `AGENTS.md` e `docs/MCP.md` para operações e limites.
