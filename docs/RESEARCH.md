# Pesquisa técnica — engine 3D local

Data da verificação: **2026-08-05**. Esta pesquisa usa repositórios, model cards e documentação dos mantenedores. Ela separa requisitos publicados de relatos da comunidade: um relato não vira requisito suportado.

## Conclusão executiva

Uma RTX 4060 de 8 GB é uma GPU Ada compatível com CUDA e com kernels modernos de atenção, mas **não possui VRAM suficiente para executar os pipelines oficiais completos de TRELLIS.2, Hunyuan3D-2.1 ou o fluxo completo de textura do Hunyuan3D-2.0**. A RTX 4060 pertence à arquitetura Ada Lovelace, e FlashAttention-2 suporta GPUs Ada; isso melhora desempenho, mas não reduz o requisito de memória dos pesos e ativações. [NVIDIA RTX 4060](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4060-4060ti/) · [FlashAttention](https://github.com/Dao-AILab/flash-attention)

## Atualização: TRELLIS 2 em todos os perfis locais

A engine usa [trellis.cpp](https://github.com/pwilkin/trellis.cpp) como
implementação local do TRELLIS 2 para 6–16 GB. O upstream documenta um fluxo
com geração de malha, UV e materiais PBR e publica um único diretório de pesos
GGUF compatível em diretórios publicados `q4/` e `q8/`. Os instaladores
Forge3D usam Q4 nos perfis 6/8 GB e baixam Q4 + Q8 nos perfis 12/16 GB; a
quantização ativa continua limitada pelo perfil e pelo preflight local.
UltraShape continua experimental: refina geometria, não conserta textura, e só
pode ser marcado como ativo após seu worker passar preflight e calibração real.

O produto deve, portanto, ter três caminhos explícitos:

1. **Rota prática de 6–16 GB, comunitária:** [`trellis.cpp`](https://github.com/pwilkin/trellis.cpp) é uma reimplementação C++/GGML do TRELLIS.2, com runtime publicado para Windows/Linux. O guia do projeto publica pesos quantizados `q4` de cerca de 6 GB e `q8` de cerca de 9,5 GB, além de `res 512` (leve) e `res 1024` (cascata). É a rota de integração para a RTX 4060, mas continua sendo comunitária/experimental — não altera o requisito oficial da Microsoft. [Guia do trellis.cpp](https://raw.githubusercontent.com/pwilkin/trellis.cpp/main/docs/getting-started.md)
2. **Fallback oficial de baixa VRAM:** geração de forma via Hunyuan3D-2 / `Hunyuan3D-2mini`, pós-processamento local e exportação. O repositório oficial informa 6 GB para geração de forma e 16 GB para forma + textura. [Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)
3. **Qualidade máxima oficialmente suportada:** TRELLIS.2 em Linux com ao menos 24 GB. Em 12/16 GB, oferecer Hunyuan3D-2.1 somente quando houver memória suficiente para a etapa solicitada, ou TRELLIS original em Linux com 16 GB; nunca habilitar o runtime Python oficial do TRELLIS.2 por padrão abaixo de 24 GB. [TRELLIS.2](https://github.com/microsoft/TRELLIS.2) · [TRELLIS](https://github.com/microsoft/TRELLIS)

Não há base oficial para prometer “excelente TRELLIS.2 completo” em uma 4060 de 8 GB. O backend deve comunicar isso antes do download e escolher o provedor por capacidade, não pelo nome exibido na interface.

## Matriz de viabilidade

| Tecnologia | Papel correto | Requisito/estado oficial relevante | Decisão para perfis 6/8/12/16 GB |
|---|---|---|---|
| [TRELLIS.2-4B](https://huggingface.co/microsoft/TRELLIS.2-4B) | imagem → mesh com materiais PBR | Linux testado; NVIDIA com **>=24 GB**; 4B parâmetros; 512³–1536³ | Bloquear em 6/8/12/16 GB; disponibilizar apenas em `24gb+`/Linux. |
| [trellis.cpp](https://github.com/pwilkin/trellis.cpp) | porta C++/GGML comunitária de TRELLIS.2; servidor HTTP local | Binaries Windows/Linux CUDA/Vulkan; guia publica `q4` ~6 GB, `q8` ~9,5 GB, `512` leve e `1024` em cascata | Rota integrada experimental: 6/8 GB `q4` + 512; 12 GB tentar `q8` + 512 após preflight; 16 GB pode testar `q8` + 1024. Não é suporte Microsoft. |
| [TRELLIS original](https://github.com/microsoft/TRELLIS) | texto/imagem → mesh, Gaussian ou radiance field | Linux testado; NVIDIA com **>=16 GB**; image-large 1.2B | 16 GB/Linux: permitido. 6/8 GB: somente experimento separado, sem garantia. |
| [UltraShape 1.0](https://github.com/PKU-YuanGroup/UltraShape-1.0) | refinamento **imagem + mesh inicial → mesh** | Não é gerador inicial; requer mesh bruto do Hunyuan3D-2.1. Há flags low-VRAM, sem mínimo publicado. | Não é backend padrão de 6/8/12/16 GB; opt-in experimental após teste real. |
| [Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) | imagem → forma + PBR | 10 GB forma, 21 GB textura, 29 GB combinado | 12/16 GB: forma somente; 24+ textura isolada; 29+ fluxo combinado oficial. |
| [Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) | fallback de geração | 6 GB forma; 16 GB forma + textura; inclui modo low-VRAM | Caminho recomendado para 6/8 GB (forma). 16 GB pode solicitar textura. |
| [BRIA RMBG 2.0](https://huggingface.co/briaai/RMBG-2.0) | recorte/alpha de imagem de entrada | 0.2B; pesos requerem aceite; CC BY-NC 4.0 para self-host | Útil em todos os perfis, mas descarregar/rodar em CPU quando a VRAM estiver reservada ao gerador. |
| [xFormers](https://github.com/facebookresearch/xformers) / [FlashAttention](https://github.com/Dao-AILab/flash-attention) | atenção eficiente | São aceleradores, não quantizadores ou modelos 3D | Optional e versionado por ambiente; não mudam os mínimos de VRAM. |
| [SageAttention](https://github.com/thu-ml/SageAttention) | atenção quantizada | kernels Ampere/Ada/Hopper; integração depende da classe de atenção do modelo | Não ativar por monkey-patch global; nenhum suporte oficial específico a TRELLIS/UltraShape foi localizado. |
| [TeaCache](https://github.com/ali-vilab/TeaCache) | cache de passos para diffusion de vídeo/imagem/áudio | Lista FLUX e vários modelos de vídeo, mas não TRELLIS, TRELLIS.2, UltraShape ou Hunyuan3D | Não integrar ao caminho 3D. |

## Modelos 3D

### TRELLIS.2

O [repositório oficial](https://github.com/microsoft/TRELLIS.2) existe e o checkpoint oficial é [`microsoft/TRELLIS.2-4B`](https://huggingface.co/microsoft/TRELLIS.2-4B), licenciado MIT. É um pipeline de imagem para asset 3D com material PBR e suporta geometria aberta, não-manifold e transparência. O modelo card declara 4B parâmetros, entrada de imagem única e exportação de mesh PBR.

Limites que afetam diretamente a implementação:

- O mantenedor declara que o código foi testado **somente em Linux** e requer GPU NVIDIA com **pelo menos 24 GB**; os testes citados são A100 e H100. Não há suporte oficial para Windows nativo ou 8 GB. [Requisitos oficiais](https://github.com/microsoft/TRELLIS.2#%EF%B8%8F-installation)
- A instalação oficial usa CUDA Toolkit recomendado 12.4, Python >=3.8, Conda, submódulos e extensões CUDA (`o-voxel`, `cumesh`, `flexgemm`, `nvdiffrast`, `nvdiffrec`). Não é uma dependência Python pura.
- A tabela de velocidade (3 s em 512³, 17 s em 1024³, 60 s em 1536³) foi medida em H100, portanto não deve ser usada como previsão para placas de consumidor.
- O model card reconhece possíveis pequenos furos/descontinuidades e que o modelo não é alinhado a preferências humanas. Ainda é necessário validar mesh, UV e textura antes de exportar. [Limitações conhecidas](https://huggingface.co/microsoft/TRELLIS.2-4B)

**Uso na engine:** implementar como provedor remoto/local opcional `trellis2_official`, desabilitado se a checagem de ambiente não encontrar Linux e 24 GB livres. Não usar CPU offload para fingir compatibilidade: isso não é uma configuração publicada pelo projeto e pode falhar nas extensões CUDA.

### trellis.cpp (porta comunitária C++/GGML)

O [trellis.cpp](https://github.com/pwilkin/trellis.cpp) é uma implementação independente, em C++/GGML, que declara portar o pipeline `microsoft/TRELLIS.2-4B`. Ele não usa Python em runtime e publica binários para Windows e Linux com backends CUDA, Vulkan e ROCm. O projeto também expõe `trellis-server`, com `GET /health` e `POST /generate`, o que é adequado para o backend local da aplicação. [README upstream](https://github.com/pwilkin/trellis.cpp) · [guia de instalação](https://raw.githubusercontent.com/pwilkin/trellis.cpp/main/docs/getting-started.md)

O guia do próprio projeto documenta três conjuntos de pesos: `f16` (~16,5 GB), `q8` (~9,5 GB, descrito pelo upstream como *near-lossless*) e `q4` (~6 GB, com pequena perda de qualidade). Ele também separa `res 512` (caminho leve) de `res 1024` (cascata). O README afirma que a cascata 1024 cabe em placa de 16 GB graças a FlashAttention; ele **não** publica uma garantia de pico de VRAM para cada combinação de quantização, GPU, imagem e resolução. Os valores de 6/9,5 GB devem ser tratados como tamanhos dos pesos/perfis quantizados publicados, não como substituto de um preflight de VRAM livre.

**Decisão de integração:** expor este provedor como `trelliscpp` e usar `q4 + 512` como rota inicial da RTX 4060 de 8 GB; deixar `q8 + 512` para 12 GB e `q8 + 1024` para 16 GB após teste de fumaça. Uma geração por GPU, nenhum upscaler/RMBG residente junto e fallback imediato se a alocação falhar. A aplicação deve rotular todos esses modos como **community / experimental**: eles podem produzir GLB PBR local, mas não são suporte ou benchmark oficial da Microsoft para TRELLIS.2 em 6–16 GB.

### TRELLIS original

O [TRELLIS original](https://github.com/microsoft/TRELLIS) é um projeto distinto: suporta prompts de texto ou imagem e pode produzir mesh, Gaussian e radiance field. O `TRELLIS-image-large` oficial possui 1.2B parâmetros; o próprio README recomenda a variante condicionada por imagem para melhor resultado. [Model card image-large](https://huggingface.co/microsoft/TRELLIS-image-large)

- Requisito publicado: Linux testado e GPU NVIDIA com **>=16 GB**; CUDA 11.8 ou 12.2 foi testado. Windows é apontado somente como instalação não totalmente testada. [Instalação oficial](https://github.com/microsoft/TRELLIS#-installation)
- O repositório permite escolher `flash-attn` ou `xformers`, mas isso não torna uma placa de 8 GB oficialmente compatível.
- Existe um relato em issue do próprio repositório sobre um fork comunitário que descarrega estágios e afirma 6–8 GB. É código não mantido pela Microsoft, pode ter OOM aleatório e o autor declara haver código gerado por IA. Ele deve ser um experimento manual separado, não um download automático da engine. [Issue #31](https://github.com/microsoft/TRELLIS/issues/31)

### UltraShape 1.0

**UltraShape 1.0 existe**: há [projeto](https://pku-yuangroup.github.io/UltraShape-1.0/), [repositório oficial PKU-YuanGroup](https://github.com/PKU-YuanGroup/UltraShape-1.0), [relatório arXiv](https://arxiv.org/abs/2512.21185) e pesos em [`infinith/UltraShape`](https://huggingface.co/infinith/UltraShape).

Seu papel é refinamento geométrico em dois estágios, não substituto direto de TRELLIS. O fluxo publicado pede primeiro uma malha grosseira gerada por **Hunyuan3D-2.1**, depois fornece imagem de referência, mesh, checkpoint e diretório de saída ao refinador. A instalação publicada fixa Python 3.10, PyTorch 2.5.1/cu121, `cubvh`; os extras de treino incluem uma wheel `torch_cluster` específica para Linux. [Instruções do projeto](https://github.com/PKU-YuanGroup/UltraShape-1.0#%EF%B8%8F-installation--usage)

O checkpoint principal `ultrashape_v1.pt` ocupa **7,37 GB** no repositório oficial de pesos (o conjunto inteiro aparece como 8,02 GB, incluindo VAE). Somado às ativações, ao VAE e ao mesh, isso não é prova de que o refinamento cabe em uma placa de 8 GB. O README oferece `--low_vram`, `num_latents=8192` e `chunk_size=2048` como tentativas de reduzir memória, mas **não declara** que cabe em 8 GB nem fornece número de VRAM. Portanto, a UI deve marcar “experimental” e permitir somente após preflight e teste de fumaça. [Arquivos dos pesos](https://huggingface.co/infinith/UltraShape/tree/main)

O contrato de entrada é obrigatório: imagem de referência, mesh inicial, checkpoint e diretório de saída; a receita publicada usa Hunyuan3D-2.1 para produzir o mesh inicial e usa 50 passos por padrão (podem ser reduzidos a 12 para acelerar). A aplicação pode oferecer um GLB do `trellis.cpp` como mesh de origem **somente como combinação customizada não validada pelo upstream** — não o chamar de fluxo oficial do UltraShape.

Há uma inconsistência de licenças que exige cautela: o model card dos pesos indica Apache-2.0, mas o arquivo [`LICENSE` do repositório](https://raw.githubusercontent.com/PKU-YuanGroup/UltraShape-1.0/main/LICENSE) é o **Tencent Hunyuan 3D 2.1 Community License Agreement**, com restrições territoriais e de redistribuição/uso. Até confirmação escrita dos autores, uma distribuição deve seguir a interpretação mais restritiva e não embutir UltraShape como componente comercial “livre”.

### Hunyuan3D como fallback oficial para baixa VRAM

UltraShape requer um mesh inicial e o candidato oficial mais diretamente indicado por seus autores é [Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1). Entretanto, esse 2.1 informa 10 GB para forma, 21 GB para textura e 29 GB para ambas as etapas. O `--low_vram_mode` existe, mas não substitui esses números publicados. Ele é adequado para 12 GB em **forma sem textura**, não para a 4060 8 GB.

Para 6/8 GB, o [Hunyuan3D-2 oficial](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) informa 6 GB para forma e 16 GB para forma + textura. Ele também oferece os checkpoints de forma menores `Hunyuan3D-2mini` (0.6B), `-Fast` e `-Turbo`, além de `--low_vram_mode`. Este é o fallback que pode fazer a engine funcionar de forma honesta nas placas menores. Pesos: [`tencent/Hunyuan3D-2`](https://huggingface.co/tencent/Hunyuan3D-2) e [`tencent/Hunyuan3D-2mini`](https://huggingface.co/tencent/Hunyuan3D-2mini).

Os pesos/código Hunyuan não são MIT/Apache: a [licença comunitária 2.1](https://raw.githubusercontent.com/Tencent-Hunyuan/Hunyuan3D-2.1/main/LICENSE) exclui UE, Reino Unido e Coreia do Sul, impõe regras de uso, exige repasse de avisos em redistribuição e requer licença adicional acima de um milhão de usuários ativos mensais. Não se deve aceitar esses termos em nome do usuário por um `.bat`.

## Pré-processamento de imagem

### BRIA RMBG 2.0

[RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0) é um modelo de segmentação/remover fundo baseado em BiRefNet. Ele entrega alpha matte de 8 bits, aceita uso com `transformers` e possui cerca de 0.2B parâmetros. Serve muito bem para preparar uma imagem centrada e com fundo removido antes da geração 3D; não cria geometria nem textura.

Os pesos self-hosted exigem login/aceite no Hugging Face e a licença indicada é **CC BY-NC 4.0**. Uso comercial exige acordo com a BRIA. A engine deve:

- manter RMBG como recurso opcional, desligável;
- indicar claramente a licença na primeira ativação;
- baixar somente após o usuário autenticar/aceitar os termos;
- executar em CPU ou liberar memória da GPU antes de carregar o gerador 3D.

### Upscalers e edição da imagem de referência

| Ferramenta | Adequação | Licença/limite verificado |
|---|---|---|
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | Melhor opção prática para ampliar ou restaurar a imagem **antes** do image-to-3D; suporta tile e FP16. | BSD-3-Clause. O projeto oferece executáveis NCNN/Vulkan para Windows/Linux/macOS e modelos oficiais. |
| [SwinIR](https://github.com/JingyunLiang/SwinIR) | SR, denoise e remoção de artefato JPEG; alternativa não generativa. | Apache-2.0. Pesos são baixados pelo script de teste. |
| [SUPIR](https://github.com/Fanghua-Yu/SUPIR) | Restaurador generativo de alta qualidade, mas pesado; seus exemplos low-VRAM ainda citam 12 GB para diffusion e 16 GB para LLaVA. | Declaração explícita de uso **não comercial**. Não é adequado ao perfil 8 GB. |
| [FLUX.1 Kontext dev](https://github.com/black-forest-labs/flux) | Edição da imagem de referência; pode ajudar a criar uma imagem limpa/consistente, mas pode alterar identidade e detalhes do objeto. Não é image-to-3D. | Pesos Kontext dev usam FLUX.1-dev Non-Commercial License; só usar opt-in. O código do repo é Apache-2.0, mas não substitui licença dos pesos. |

Nunca usar upscaling generativo como garantia de geometria melhor: artefatos/alucinações na imagem de entrada se propagam para o mesh. Para 6/8 GB, usar `tile` e um tamanho de entrada moderado, testar visualmente e manter a imagem original disponível para comparação.

## Aceleração e offload

### FlashAttention, xFormers e SageAttention

[FlashAttention-2](https://github.com/Dao-AILab/flash-attention) suporta CUDA em GPUs Ampere, Ada e Hopper, portanto é compatível em princípio com a arquitetura da RTX 4060. Requer PyTorch >=2.2, CUDA >=12 para a rota CUDA e informa que Linux é a plataforma esperada; compilação no Windows “pode funcionar”, mas ainda requer mais testes. Ele é BSD-3-Clause.

[xFormers](https://github.com/facebookresearch/xformers) oferece atenção exata eficiente em memória. A instalação binária atual declarada pelo projeto para Windows/Linux exige PyTorch 2.10, enquanto TRELLIS e UltraShape fixam versões bem mais antigas de PyTorch/CUDA. Não instalar “a versão mais nova” globalmente: cada backend deve ter ambiente isolado e versões travadas. Use `python -m xformers.info` como diagnóstico.

[SageAttention](https://github.com/thu-ml/SageAttention) tem kernels para Ampere/Ada/Hopper e requer Python >=3.9, Torch >=2.3, Triton >=3.0; para FP8 em Ada pede CUDA >=12.4. A documentação alerta que nem todo modelo funciona ao substituir globalmente `scaled_dot_product_attention`; a classe de atenção do modelo deve ser alterada de forma específica. Não foi localizado suporte oficial de SageAttention para TRELLIS/TRELLIS.2/UltraShape, portanto é uma otimização futura submetida a benchmark de fidelidade e regressão, não uma dependência padrão.

**Política aplicada:** usar somente o backend de atenção publicado pelo provedor e exigir importação mais inferência real. No UltraShape não há fallback SDPA: `flash_attn`, `sageattention` e `cubvh` precisam importar no ambiente upstream PyTorch 2.5.1/cu121, e qualquer falha mantém o refinador indisponível. Não carregar ou substituir kernels por monkey-patch.

### TeaCache

[TeaCache](https://github.com/ali-vilab/TeaCache) é uma técnica training-free que faz cache entre timesteps para modelos de diffusion de vídeo, imagem e áudio. O repositório lista FLUX, Lumina, Wan, CogVideoX, HunyuanVideo e outros; **não lista TRELLIS, TRELLIS.2, UltraShape ou Hunyuan3D**. A licença do projeto é Apache-2.0, mas as licenças dos modelos compatíveis continuam valendo.

Conclusão: TeaCache pode ser considerado somente se a engine acrescentar, no futuro, uma rota FLUX de edição de imagem. Ele não deve ser apresentado como acelerador da geração 3D atual.

### Accelerate CPU/disk offload

[`accelerate.cpu_offload`](https://huggingface.co/docs/accelerate/package_reference/big_modeling) mantém um `state_dict` no CPU e move parâmetros para a GPU conforme necessário. Isso reduz VRAM, mas torna a execução limitada por PCIe/RAM e só funciona quando a arquitetura do pipeline foi integrada de modo compatível. Não resolve extensões CUDA, picos de ativação ou modelos que chamam pesos fora dos módulos registrados.

Usar apenas atrás de uma flag `experimental_offload`, com RAM suficiente, uma tarefa por GPU, telemetria de tempo/OOM e fallback limpo. Não deve ser usado para liberar TRELLIS.2 em 8 GB nem mudar a matriz de requisitos publicada.

## Mesh, UV, retopologia e exportação

### xatlas

[xatlas](https://github.com/jpcy/xatlas) é uma biblioteca C++11 sem dependências externas para gerar UVs únicos destinados a baking/lightmaps/textura. É MIT. Em uma engine Python, usar binding confiável ou processo próprio; não acoplar uma DLL compilada manualmente ao backend sem teste de plataforma.

Regra de fluxo: se a topologia mudar, UVs e texturas antigos podem se tornar inválidos. Primeiro retopologar/decimar, depois gerar UV (xatlas/Blender) e então rebake ou gerar textura. Para um GLB já PBR gerado por TRELLIS.2, não refazer UV sem necessidade.

### Blender

[Blender](https://www.blender.org/) é GPL; a GPL aplica-se ao aplicativo, não às obras artísticas produzidas por ele. Ele pode ser invocado em background para importação, limpeza, validação e exportação; use a documentação de [linha de comando](https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html) compatível com a versão instalada.

Como processo de servidor, chamar o executável em background e um script Python próprio com argumentos validados. Não usar `bpy` de um interpretador Python externo. O backend deve possuir timeout, diretório temporário por job e validação do GLB final.

### Instant Meshes e QuadriFlow

[Instant Meshes](https://github.com/wjakob/instant-meshes) é uma aplicação interativa de retopologia alinhada a campos, com binários Windows/macOS/Linux e licença BSD-3-Clause. É útil para operador humano, não para uma etapa automatizada confiável de produção.

[QuadriFlow](https://github.com/hjwdzh/QuadriFlow) recebe mesh triangular manifold e gera mesh quad manifold; suporta build CMake em Windows/Linux/macOS e é MIT, com ressalvas para dependências. O próprio projeto observa que remoção SAT de flips é Unix-only. O [manual do Blender](https://docs.blender.org/manual/en/latest/modeling/meshes/retopology.html) também descreve QuadriFlow como mais lento e inadequado para limpar interseções ou produzir a topologia final de personagens animáveis.

Portanto: manter retopologia automática como job opcional, nunca como condição para o primeiro preview, e avisar que atributos/UV/materiais podem ser perdidos e requerer rebake.

## Licenças, pesos e download responsável

| Item | Onde obter | Situação que a instalação deve respeitar |
|---|---|---|
| TRELLIS.2-4B | [Hugging Face Microsoft](https://huggingface.co/microsoft/TRELLIS.2-4B) | MIT; ainda respeitar licenças das dependências `nvdiffrast`/`nvdiffrec`. |
| trellis.cpp / GGUF | [código upstream](https://github.com/pwilkin/trellis.cpp), [pesos GGUF](https://huggingface.co/ilintar/trellis2-gguf) | Porta comunitária MIT; revisar a licença marcada como `other` no repositório GGUF e registrar release/revisão. Não confundir com suporte Microsoft. |
| TRELLIS image/text | [image-large](https://huggingface.co/microsoft/TRELLIS-image-large), [text-large](https://huggingface.co/microsoft/TRELLIS-text-large) | MIT; confirmar integridade/estrutura depois do download. |
| UltraShape | [Hugging Face](https://huggingface.co/infinith/UltraShape) | Card Apache-2.0 versus LICENSE do código Tencent: registrar conflito, não redistribuir automaticamente. |
| Hunyuan3D | [2.0](https://huggingface.co/tencent/Hunyuan3D-2), [2.1](https://huggingface.co/tencent/Hunyuan3D-2.1) | Licença comunitária Tencent e termos de território/uso/redistribuição. |
| RMBG 2.0 | [BRIA model card](https://huggingface.co/briaai/RMBG-2.0) | Pesos gated; CC BY-NC 4.0 para self-host; licença comercial separada. |
| Real-ESRGAN | [releases oficiais](https://github.com/xinntao/Real-ESRGAN/releases) | BSD-3-Clause. |
| SwinIR | [model zoo oficial](https://github.com/JingyunLiang/SwinIR) | Apache-2.0. |
| SUPIR | [repositório oficial](https://github.com/Fanghua-Yu/SUPIR) | Declaração de não uso comercial e pesos dependentes. |
| FLUX Kontext dev | [BFL](https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev) | Peso sob licença FLUX.1-dev não comercial; aceitar/acompanhar termos da BFL. |

Um instalador pode baixar software permissivamente licenciado, mas **não deve aceitar automaticamente termos gated, comunitários ou não comerciais**. Ele deve abrir a URL, pedir login/aceite quando aplicável e registrar qual versão/commit foi baixado. Fixar revisão e validar hash sempre que o fornecedor publicar hashes.

## Regras de arquitetura derivadas da pesquisa

1. Criar provedores independentes (`trelliscpp`, `hunyuan2_shape`, `hunyuan21_shape`, `trellis_original`, `trellis2_official`, `ultrashape_refine`) com `is_available()` que confere SO, VRAM livre, pesos e licença aceita.
2. Uma fila de GPU e uma geração por vez. A limpeza entre etapas deve descarregar modelos, sincronizar CUDA e liberar cache; não manter RMBG, upscaler e gerador 3D residentes ao mesmo tempo em placas pequenas.
3. Todas as etapas pesadas devem rodar em subprocesso isolado, com saída estruturada, timeout e arquivos em diretório de job. Nunca concatenar prompt/caminho enviado pelo usuário em um comando de shell.
4. A UI deve mostrar “forma”, “textura/PBR” e “refinamento” como etapas distintas, porque seus requisitos de VRAM e licenças são distintos.
5. O status “pronto” só deve aparecer após validar exportação `.glb/.obj`, existência de faces, índices válidos, UV quando necessário e abertura de fumaça no Blender/validador escolhido.
