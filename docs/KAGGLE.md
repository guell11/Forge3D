# Forge3D no Linux T4 e Kaggle

## Notebooks para rodar na nuvem

| Ambiente | Notebook | Acelerador compatível |
|---|---|---|
| Kaggle | [Forge3D_Kaggle_T4.ipynb](../notebooks/Forge3D_Kaggle_T4.ipynb) | NVIDIA T4 + Internet ativada |
| Google Colab | [Forge3D_Colab_GPU.ipynb](../notebooks/Forge3D_Colab_GPU.ipynb) | GPU NVIDIA CUDA com aproximadamente 8 GiB de VRAM ou mais |

No Colab, abra o [notebook no Colab](https://colab.research.google.com/github/guell11/Forge3D/blob/main/notebooks/Forge3D_Colab_GPU.ipynb), selecione **Runtime → Change runtime type → GPU** e execute **Run all**. Esse link do GitHub estará disponível quando a versão nova for publicada na branch `main`. Ambos os notebooks instalam os componentes, solicitam o token ngrok com entrada oculta e imprimem a URL da interface, o token temporário e o link autenticado `/agent/SKILL.md`.

**Google TPU v5e-1/v5e-8 não é suportada pelo gerador.** O runtime atual `trellis.cpp` usa binários CUDA; portar a inferência para TPU exige implementar kernels/backend para XLA ou JAX e validar os resultados. Não existe conversão automática de CUDA para TPU. Os notebooks são explicitamente voltados a GPUs NVIDIA.

O link `/agent/SKILL.md` é protegido por autenticação; forneça o token ao agente por meio seguro, não em URL, código versionado nem notebook público. O armazenamento e os dados do notebook em nuvem não são locais.

Notebook pronto: [`notebooks/Forge3D_Kaggle_T4.ipynb`](../notebooks/Forge3D_Kaggle_T4.ipynb).

## Início rápido (sem configurar caminhos)

1. Faça upload do notebook `Forge3D_Kaggle_T4.ipynb` no Kaggle e escolha GPU **T4** com **Internet** ativada.
2. Se quiser executar **este código local atualizado**, crie um dataset privado com `artifacts/Forge3D_Kaggle_Source.zip` e anexe ao notebook. O arquivo será detectado automaticamente; sem dataset, o notebook clona o GitHub.
3. Em **Add-ons → Secrets**, adicione `NGROK_AUTHTOKEN` (da conta ngrok) e `FORGE3D_ACCESS_TOKEN` (senha forte de pelo menos 32 caracteres). Sem secrets anexados, o notebook pede os valores em campo protegido.
4. Clique em **Run All**. Quando aparecer o endereço HTTPS, abra-o, autentique-se e gere modelos na interface.

O primeiro início baixa runtime e pesos GGUF e demora mais. A sessão Kaggle é temporária; interromper a GPU encerra o Forge3D.

## Kaggle

1. Abra notebook no Kaggle, habilite **Internet** e selecione **GPU T4**.
2. Adicione e anexe dois secrets em **Add-ons → Secrets**: `NGROK_AUTHTOKEN` e `FORGE3D_ACCESS_TOKEN`. Use no mínimo 32 caracteres ASCII para o segundo token. Notebook usa `UserSecretsClient.get_secret`; se um secret não estiver anexado, pede o valor com `getpass`.
3. Execute células em ordem. Por padrão, notebook clona `https://github.com/guell11/Forge3D.git`; selecione branch/tag com `FORGE3D_GIT_REF` quando necessário. Para testar source atual ainda não enviado ao Git, baixe o [ZIP do workspace](../artifacts/Forge3D_Kaggle_Source.zip), carregue-o como dataset privado e anexe o dataset ao notebook. Kaggle extrai arquivos ZIP de dataset antes de montá-los; a raiz montada passa a conter `backend/`, `frontend/` e `scripts/`. Antes da célula **Obter código atual**, adicione e execute esta célula de configuração:

   ```python
   import os
   os.environ["FORGE3D_SOURCE_DIR"] = "/kaggle/input/<slug-do-dataset>"
   ```

   Esse modo importa source sem precisar de Git nem procurar subpastas. Se um ZIP bruto estiver montado, configure `os.environ["FORGE3D_SOURCE_ZIP"]` no lugar; defina apenas uma das variáveis. O ZIP contém código atual sem pesos, secrets, outputs ou ambientes gerados; gere ZIP novo após novas alterações.
4. Se `/kaggle/working/Forge3D` já existir, mova ou remova manualmente antes de importar o ZIP ou clonar. Notebook não sobrescreve diretório existente.
5. Abra a URL HTTPS impressa. Tela de login aceita `FORGE3D_ACCESS_TOKEN`. A sessão dura oito horas; cookie é `HttpOnly`, `SameSite=Strict` e recebe `Secure` quando ngrok encaminha HTTPS.
6. Execute a célula **Encerrar** antes de parar o notebook para fechar túnel e serviço. Encerrar sessão Kaggle também interrompe ambos.

Notebook instala `trellis.cpp` CUDA e o perfil 8gb existente: Q4, geometria 512, atlas 1024, GPU física 0 exposta como único dispositivo CUDA lógico `0`. Não soma VRAM de T4x2. Antes do instalador, usa Node já compatível ou baixa distribuição oficial Node 22 LTS e confere SHA-256 do manifesto upstream. A UI/API/GLB compartilham uma origem; o wrapper ASGI exige cookie de sessão ou `Authorization: Bearer ...` para API, EventSource, assets e saídas.

Os dez arquivos GGUF Q4 atualmente referenciados pelo instalador somam cerca de 6,1 GiB pelos `Content-Length` retornados pelo Hugging Face. Notebook exige 10 GiB livres em `/kaggle/working` antes de baixar, para deixar espaço ao runtime, cache e resultados. Tamanho e disponibilidade podem mudar no repositório upstream.

## Linux T4 manual

Instale dependências e modelo pelo instalador existente, então crie build estático com API relativa:

```bash
bash 'instalação/install.sh' --profile 8gb
cd frontend
VITE_API_BASE_URL=/api npm run build
cd ..
read -rsp 'Forge3D access token: ' FORGE3D_ACCESS_TOKEN; echo
export FORGE3D_ACCESS_TOKEN
bash scripts/run-t4.sh
```

`run-t4.sh` verifica T4 em GPU zero, runtime e pesos Q4, desativa autostart de `trellis-server` e UltraShape, fixa perfil 8gb, resolution 512 e `CUDA_VISIBLE_DEVICES=0`, então serve o frontend e API em `http://127.0.0.1:7860`. Node.js precisa ser 20.19+ ou 22.12+. Mantenha serviço em loopback; notebook estabelece o túnel ngrok e aplica autenticação no ingresso.

## FaithC opcional

Célula de FaithC vem desligada. Para habilitar, altere `ENABLE_FAITHC = False` para `True` e execute a célula antes de iniciar o servidor. Ela cria `.venv-faithc` separado, instala ferramentas de build, Torch `2.5.1+cu124`, wheel `torch-scatter` compatível e `backend/requirements-faithc.txt` com `--no-build-isolation` e `TORCH_CUDA_ARCH_LIST=7.5`. Executa probe que importa FaithC/Atom3d e faz alocação CUDA; a célula falha se probe não confirmar T4. Servidor recebe `FAITHC_ENABLED=1`, `FAITHC_PYTHON` e `FAITHC_WORKER`. Comece com resolução 256. Essa instalação e execução não foram validadas em uma T4 neste workspace.

## Integração por bridge MCP

Configure `FORGE3D_API_URL` com somente a origem HTTPS do túnel, sem caminho `/api` (por exemplo, `https://<host-ngrok>`). A bridge acrescenta `/api/...` a cada chamada; incluir `/api` na variável produz `/api/api/...` e retorna 404. Configure `FORGE3D_API_TOKEN` na bridge com o mesmo valor bruto de `FORGE3D_ACCESS_TOKEN` usado pelo serviço, sem prefixo `Bearer `. Gateway de [scripts/serve_remote.py](../scripts/serve_remote.py) valida esse bearer em chamadas server-to-server. Browser usa cookie de sessão para EventSource e downloads; EventSource nativo não permite configurar header Bearer. Veja [configuração da bridge MCP](MCP.md#remote-api).

## Validação e limites

Links upstream conferidos em 9 out. 2026: [Kaggle Secrets e UserSecretsClient](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md#using-secrets-in-kernels), [ngrok Python SDK](https://github.com/ngrok/ngrok-python), [Trellis.cpp releases](https://github.com/pwilkin/trellis.cpp/releases) e [Trellis.cpp README](https://github.com/pwilkin/trellis.cpp). A release upstream descreve bundle CUDA para GPUs NVIDIA Turing e posteriores; T4 é a classe visada pelo caminho. URLs do bundle e dos dez arquivos Q4 responderam HTTP 200 durante a preparação deste notebook.

Kaggle documenta a extração de arquivos ZIP de datasets antes do uso em notebooks em [Datasets](https://www.kaggle.com/docs/datasets); por isso, `FORGE3D_SOURCE_DIR` aponta à raiz montada, sem extensão `.zip`.

Build CUDA, inferência TRELLIS, túnel externo e FaithC não foram executados neste workspace Windows. O notebook executa preflight de GPU, `trellis-cli --help`, health HTTP autenticado, recusa sem token, login/cookie, UI e rota de saída antes de abrir ngrok. Sessão Kaggle pode ser encerrada por limites do serviço; mantenha o notebook conectado enquanto usa o endpoint.
