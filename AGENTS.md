# Forge3D para agentes de IA

Use a API Forge3D para consultar capacidades, enviar imagens, criar e acompanhar jobs e baixar saídas. A bridge MCP só traduz chamadas para a API; geração e operações rodam no servidor Forge3D e usam sua fila GPU serial. Capacidades descrevem a instalação atual, mas não garantem que uma execução termine.

## Descoberta e ferramentas MCP

Comece com `describe_api` para ler rotas, schemas Pydantic e limites publicados. Depois chame `capabilities` antes de escolher qualidade, FaithC ou operação. Use os schemas retornados pelo servidor como contrato atual.

A bridge MCP registra estas 11 ferramentas:

| Ferramenta | Uso |
| --- | --- |
| `describe_api` | Lê manifesto, rotas, schemas e limites da API. |
| `capabilities` | Lê perfis, pipeline, limite de upload e disponibilidade por operação. |
| `upload_image(path)` | Envia PNG, JPEG, WEBP ou BMP do sistema de arquivos onde a bridge roda. |
| `generate_model(upload_id, options?, adapter?, output_format?, prompt?)` | Valida e enfileira geração; retorna metadados do job. |
| `list_jobs(limit?, offset?, search?, status?, favorite?)` | Lista resumos paginados; use `get_job` para detalhes completos. |
| `get_job(job_id)` | Lê status e registro completo do job. |
| `wait_job(job_id, timeout_seconds?)` | Espera estado terminal por até 25 s; timeout não cancela o job. |
| `cancel_job(job_id)` | Solicita cancelamento de job queued ou running. |
| `create_operation(job_id, kind, ...)` | Enfileira operação suportada sobre modelo concluído. |
| `download_model(job_id, destination)` | Baixa o modelo principal para caminho local, sem sobrescrever arquivo existente. |
| `download_artifact(job_id, filename, destination)` | Baixa artefato cujo nome aparece em `job.artifacts`, sem sobrescrever arquivo existente. |

Parâmetros e schemas completos vêm de `describe_api`; os parâmetros MCP também aparecem em `tools/list`. IDs de upload e job são strings hexadecimais de 32 caracteres retornadas pela API. Não invente IDs, resultados, métricas ou estados.

## Fluxo de geração

1. Consulte `describe_api` e `capabilities`. Escolha somente qualidade disponível e opções aceitas pelo schema/capacidades atuais. Consulte `capabilities` novamente se o estado da instalação puder ter mudado.
2. Chame `upload_image` com um caminho de arquivo local legível pela bridge. A API devolve `upload.id`; use esse ID em `generate_model`.
3. Chame `generate_model`. Exemplo de argumentos MCP, substituindo o placeholder pelo ID real retornado:

   ```json
   {
     "upload_id": "<UPLOAD_ID retornado por upload_image>",
     "adapter": "auto",
     "output_format": "glb",
     "options": { "faithc": "off" }
   }
   ```

4. Guarde `job.id`. Chame `wait_job(job_id, timeout_seconds=20)` e leia `terminal`, `timed_out` e o status do job. Se `timed_out` for `true`, job continua ativo; aguarde de novo ou consulte `get_job`/`list_jobs`.
5. Só quando status for `completed`, baixe o principal com `download_model`. Use `download_artifact` apenas com um `filename` listado em `job.artifacts`.

Não repita `upload_image`, `generate_model`, `create_operation` ou `cancel_job` automaticamente após timeout de rede ou resposta ambígua: servidor pode ter aceitado o POST. Para geração/operação, confira `list_jobs` e confirme candidato com `get_job`; para cancelamento, confira `get_job`. Se não identificar com segurança o job afetado, pare e peça orientação. A API não oferece chave de idempotência; não existe listagem pública de uploads para resolver um upload ambíguo.

## REST e schemas

Use `FORGE3D_API_URL` como origem HTTP(S) da API, sem `/api`, query ou fragmento. Rotas principais:

| Método e rota | Função |
| --- | --- |
| `GET /api/agent-manifest` | Manifesto, schemas de geração/operação e limites de wait/upload. |
| `GET /openapi.json` | Catálogo OpenAPI completo. |
| `GET /api/capabilities` | Perfil, pipeline e limites dinâmicos. |
| `GET /api/operations/capabilities` | Disponibilidade atual por operação. |
| `POST /api/uploads` | Multipart com campo `file`; retorna `upload.id`. |
| `POST /api/jobs` | Corpo `CreateJobRequest`; retorna job enfileirado. |
| `GET /api/jobs` | Lista paginada; aceita filtros `limit`, `offset`, `search`, `status` e `favorite`. |
| `GET /api/jobs/{job_id}/wait?timeout_seconds=20` | Espera até 25 s e retorna `{job, terminal, timed_out}`. |
| `GET /api/jobs/{job_id}` | Lê registro completo. |
| `POST /api/jobs/{job_id}/cancel` | Solicita cancelamento. |
| `POST /api/jobs/{job_id}/operations` | Corpo `OperationRequest`; retorna job derivado. |
| `GET /api/jobs/{job_id}/download` | Baixa saída principal concluída. |
| `GET /api/jobs/{job_id}/artifacts/{filename}/download` | Baixa artefato registrado no job. |

Exemplo REST de criação, após upload e substituição do placeholder por `upload.id`:

```json
{
  "upload_id": "<UPLOAD_ID retornado por POST /api/uploads>",
  "adapter": "auto",
  "output_format": "glb",
  "options": { "faithc": "off" }
}
```

Envie somente campos previstos no schema de `describe_api`. `GET /api/capabilities` e `GET /api/operations/capabilities` refletem configuração observada; não substituem a validação do POST nem garantem sucesso de inferência.

## Operações e arquivos

Operações aceitas: `split`, `simplify`, `remesh`, `retexture` e `transform`. Antes de criar uma, consulte disponibilidade para aquele tipo e confirme que job pai terminou com GLB. O novo job tem `parent_job_id`; ele cria uma saída derivada e preserva o arquivo do job pai. `simplify` reduz ao teto pedido; `remesh` reconstrói topologia.

Exemplo de chamada MCP transform com valores de identidade, substituindo o placeholder por um job concluído:

```json
{
  "job_id": "<JOB_ID concluído com GLB>",
  "kind": "transform",
  "transform": {
    "translation": [0, 0, 0],
    "rotation_degrees": [0, 0, 0],
    "scale": [1, 1, 1]
  }
}
```

`options.faithc` aceita `off` ou `geometry`. Ative `geometry` só se `capabilities` disser que FaithC está configurado. FaithC produz artefato de geometria separado, sem UV/PBR, e não substitui o GLB principal. Consulte `validation` para saber quais mapas PBR foram encontrados nesse GLB. O download principal e cada artefato têm rotas próprias.

`upload_image.path` e os destinos de download são caminhos vistos pelo processo MCP, não pelo navegador. Em configuração local, bridge, API e arquivos podem estar no mesmo computador. Com API remota, o upload viaja até o servidor; registros e resultados ficam no armazenamento configurado naquele servidor (por exemplo, no ambiente Kaggle), enquanto `download_model`/`download_artifact` gravam cópia no computador onde a bridge roda. URLs retornadas pela API não mudam esse comportamento.

## Instalação e acesso

Instale a bridge opcional a partir de `backend`:

```powershell
python -m venv .venv-mcp
.venv-mcp\Scripts\python.exe -m pip install -r requirements-mcp.txt
```

No Linux/macOS, use `.venv-mcp/bin/python`. Configure um cliente MCP local por STDIO usando os exemplos em [`docs/examples`](docs/examples/) e substitua caminho do checkout. A API local padrão é `http://127.0.0.1:8000`. STDIO inicia a bridge; `FORGE3D_API_URL` aponta para a API REST, não para um endpoint MCP.

Exemplo local no processo do cliente:

```powershell
$env:FORGE3D_API_URL = "http://127.0.0.1:8000"
```

Para usar endpoint remoto, defina variáveis no ambiente do cliente antes de iniciá-lo:

```powershell
$env:FORGE3D_API_URL = "https://<origem-do-servidor>"
$env:FORGE3D_API_TOKEN = "<FORGE3D_ACCESS_TOKEN bruto>"
```

No Bash/zsh, use `export FORGE3D_API_URL="https://<origem-do-servidor>"` e `export FORGE3D_API_TOKEN="<FORGE3D_ACCESS_TOKEN bruto>"`.

Para host não-loopback, bridge exige HTTPS e `FORGE3D_API_TOKEN` com o valor bruto, sem prefixo `Bearer `. Use origem sem `/api`; bridge envia `Authorization: Bearer ...` e bloqueia redirects. Guarde segredo em ambiente protegido, nunca em arquivo versionado. A API REST normal não valida Bearer por conta própria: token só autentica se um gateway/proxy confiável validar. `scripts/serve_remote.py` usa `FORGE3D_ACCESS_TOKEN`; configure o mesmo segredo no gateway e em `FORGE3D_API_TOKEN` da bridge. Para exemplo Kaggle, veja [`docs/KAGGLE.md`](docs/KAGGLE.md#integração-por-bridge-mcp).

## Limites, erros e validação

- Limite da API para upload é dinâmico em `capabilities.api.limits.max_upload_mb` ou no manifesto. Bridge também limita arquivo local a 512 MiB. `download_model` e `download_artifact` limitam transferência a 1 GiB. Downloads recusam destino existente.
- `wait_job.timeout_seconds` aceita 0–25 s, padrão 20. `timed_out: true` é espera encerrada, não cancelamento nem falha.
- `401`/`403`: verifique gateway, cookie/token e se gateway protege a origem correta. A API normal não autentica Bearer sozinha.
- `404`: job/upload/artefato não existe, arquivo foi removido, nome não pertence a `job.artifacts` ou URL foi montada com `/api/api/...`.
- `409`: estado do job ou disponibilidade não permite operação. Consulte job/capacidades antes de nova tentativa.
- `413`: upload excedeu limite publicado. Consulte capabilities para limite atual.
- `422`: schema, opção, perfil, formato ou requisito do worker inválido/indisponível. Leia `detail` e schema/capacidades atuais; não repita o mesmo payload sem correção.
- Timeout HTTP/transporte pode ocorrer depois que um POST foi aceito. Consulte jobs antes de tentar novamente.

Validação MCP sem inferência/GPU: em `backend`, instale dependências de teste na venv e execute a suite. No Windows PowerShell:

```powershell
.venv-mcp\Scripts\python.exe -m pip install -r requirements-mcp.txt -r requirements-dev.txt
.venv-mcp\Scripts\python.exe -m pytest tests/test_mcp.py
```

No Linux/macOS, use `.venv-mcp/bin/python` nos mesmos comandos. Suite cobre a bridge e contrato mockado/STDIO; não valida GPU ou execução de modelo. Testes REST estão em `backend/tests`.
