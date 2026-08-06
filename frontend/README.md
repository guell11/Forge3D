# Forge3D Local — frontend

Interface local para transformar uma imagem em um modelo 3D. Ela foi construída com React, Vite, TypeScript e um visualizador WebGL baseado em Three.js.

## Executar isoladamente

```powershell
cd frontend
npm install
npm run dev
```

Abra `http://127.0.0.1:5173`. O `run.bat` do projeto principal deve iniciar backend e frontend juntos quando o repositório estiver preparado.

## Conexão com a API

Por padrão, a interface procura o backend em `http://127.0.0.1:8000`. Para mudar o endereço, copie `.env.example` para `.env` e ajuste:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

O valor pode terminar com `/api` ou não. A interface usa este contrato local:

| Método | Rota | Uso |
| --- | --- | --- |
| `GET` | `/api/health` | Indica se o motor está disponível e se está em modo demonstração. |
| `POST` | `/api/uploads` | Envia uma imagem como `multipart/form-data`, no campo `file`. |
| `POST` | `/api/jobs` | Cria uma geração com adaptador e opções. |
| `GET` | `/api/jobs/{id}` | Atualiza a barra de progresso a cada 1,5 s. |
| `POST` | `/api/jobs/{id}/cancel` | Cancela uma geração ativa. |
| `GET` | `/api/jobs/{id}/download` | Baixa o arquivo final quando o trabalho estiver concluído. |

Se o backend ou os pesos dos modelos ainda não estiverem instalados, a interface continua abrindo: mostra o estado offline, conserva a imagem selecionada e mantém uma prévia geométrica no visualizador. Quando um trabalho retorna uma URL de saída GLB, ela é carregada automaticamente no canvas 3D.

## Perfil de VRAM

O perfil de memória não é escolhido na interface. Ele é configurado pelo instalador que você executou dentro de `instalação`:

- `bat-low-vram-6gb.bat`
- `bat-8gb-vram.bat` (recomendado para RTX 4060 de 8 GB)
- `bat-12gb-vram.bat`
- `bat-16gb-vram.bat`

A tela apenas informa o perfil ativo. O backend também fixa cada geração no perfil instalado, mesmo se outro valor for enviado diretamente à API.

## Verificar a compilação

```powershell
npm run build
```
