# Backend Forge3D

API FastAPI local para jobs image-to-3D serializados na GPU. O backend mantém uploads, resultados, manifestos e logs no disco local e nunca substitui silenciosamente um modelo real por demo.

## Contratos principais

| Rota | Uso |
|---|---|
| `GET /api/health` | perfil ativo e saúde da fila |
| `GET /api/capabilities` | qualidades TRELLIS instaladas, worker UltraShape e motivos de indisponibilidade |
| `POST /api/uploads` | recebe a imagem de referência |
| `POST /api/jobs` | cria job TRELLIS com `options.trellis_quality_id` e `options.ultrashape` |
| `GET /api/jobs/{id}` | etapas, ferramenta atual, ETA, fallback, auditoria e artefatos |
| `POST /api/jobs/{id}/cancel` | cancela job pendente ou em execução |

Exemplo de job:

```json
{
  "upload_id": "<id>",
  "adapter": "trellis",
  "pipeline_mode": "trellis_detail",
  "output_format": "glb",
  "options": {
    "trellis_quality_id": "detailed",
    "ultrashape": "auto",
    "seed": 42
  }
}
```

`ultrashape` aceita `auto` ou `off`. O valor legado `refine: true` continua compatível e significa `auto`, salvo quando `ultrashape: off` for explícito.

## Segurança de VRAM

O backend executa um job de GPU por vez. Antes de UltraShape, ele exige que o processo TRELLIS gerenciado tenha sido encerrado com confirmação. Sem essa confirmação, o job preserva o GLB TRELLIS e registra o fallback; ele não inicia dois modelos na GPU.

## Auditoria

Todo GLB é analisado quanto à assinatura, cena, malhas, vértices, triângulos, UVs, imagens, materiais e mapas Base Color, Metal/Roughness, Normal e Occlusion. O relatório representa somente dados que existem no arquivo exportado.

## Desenvolvimento

```powershell
cd backend
..\.venv\Scripts\python -m pytest -q
```

Os testes não precisam de CUDA, pesos ou internet. O teste real de TRELLIS/UltraShape é feito pelo instalador local correspondente ao perfil.
