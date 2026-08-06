# Manual Forge3D

## Fluxo de geração

1. Escolha o instalador correspondente à VRAM. Esse passo define o limite físico da engine.
2. Envie uma imagem de um objeto isolado, grande no quadro e com fundo simples. Objetos múltiplos ou fundos ligados ao assunto podem resultar em peças soltas e textura inconsistente.
3. Selecione uma qualidade TRELLIS disponível. A interface mostra apenas resoluções e atlas declarados no perfil instalado.
4. Use **UltraShape: Automático** para pedir refinamento quando o worker passou no preflight; use **Só TRELLIS** para evitar a etapa extra.
5. Aguarde a auditoria. Exporte apenas resultados marcados como validados.

## O que cada etapa significa

| Etapa | Ferramenta | Resultado honesto |
|---|---|---|
| Verificando imagem | Forge3D | valida entrada e avisa composição difícil |
| TRELLIS gerando malha/UV/PBR | trellis.cpp | GLB base local |
| Liberando VRAM | supervisor Forge3D | encerra o processo TRELLIS gerenciado antes do refinador |
| UltraShape refinando geometria | UltraShape | somente se worker, checkpoint e preflight estiverem válidos |
| Conferindo materiais | auditor Forge3D | preserva o GLB TRELLIS quando o refinamento não mantiver UV/PBR |
| Validando GLB | auditor Forge3D | verifica assinatura, cena, malha, UV e materiais |

Uma barra indeterminada indica que a ferramenta não fornece porcentagem interna. O tempo decorrido é real; a ETA vem da mediana de jobs locais ou da calibração inicial.

## Diagnóstico

- **“UltraShape indisponível”**: o Forge3D usará TRELLIS base. Veja o motivo no painel de propriedades; os casos comuns são Python 3.10, Build Tools, CUDA, checkpoint, preflight ou liberação de VRAM.
- **OOM**: feche programas que usam a GPU, execute o instalador do perfil correto e escolha a qualidade menor disponível. Não force um perfil superior pela interface.
- **Malha sem textura / Normal ausente**: é o relatório verdadeiro do GLB. Normal maps não são inventados para mascarar falta de detalhe.
- **Várias peças soltas**: recorte a imagem para ter um objeto central, fundo uniforme e pouca sobreposição.

### Limite real do perfil RTX 4060 / 8 GB

O perfil de 8 GB é um caminho **seguro**, não o preset de máxima fidelidade do
`trellis.cpp`: usa GGUF Q4, resolução geométrica 512 e atlas PBR 1024. No
runtime upstream, 512 é explicitamente o caminho leve; a cascata 1024 é a
rota de geometria mais nítida e o próprio projeto a documenta para 16 GB.
Assim, uma construção complexa com muitas peças pequenas (telhas, folhas,
janelas, galhos) divide um único atlas 1K entre milhares de ilhas UV e perde
nitidez de textura mesmo quando o GLB passa na auditoria.

- Mantenha **xatlas**; `Box UV` é mais rápido, mas tem empacotamento mais
  frouxo e não recupera detalhe.
- Em *Opções avançadas*, desmarque **Texturas WebP** se a prioridade for
  fidelidade do arquivo exportado: o resultado passa a usar PNG sem perdas e
  fica maior no disco. Isso não cria detalhes novos nem aumenta a VRAM.
- Não use `--decim 0`, F32, Q8 ou `--res 1024` como tentativa de "ultra" em
  uma RTX 4060 de 8 GB. Esses ajustes não são um refinador de textura e podem
  exceder a memória do perfil. Para mais geometria e atlas 2K, use o perfil
  de 16 GB após preflight; para um objeto complexo em 8 GB, prefira uma
  referência simples, com uma silhueta única e poucos microdetalhes.

Referências: [trellis.cpp — Usage](https://github.com/pwilkin/trellis.cpp#usage)
e [TRELLIS.2 oficial — requisitos e exportação](https://github.com/microsoft/TRELLIS.2#-installation).

## Histórico, controles e operações

- **Ativos** persiste todos os manifests locais; permite buscar, favoritar, reabrir, exportar e excluir com confirmação.
- O painel avançado envia diretamente ao `trellis-cli`: seed, background removal, xatlas/box UV, max-tokens, remesh band, decimation grid, atlas/textura, WebP, GSS/GSH, FlashAttention e F32. A interface não inventa controles de temperatura ou sampling steps que o binário instalado não publica; GSS/GSH são os controles reais de guidance, e F32 só é aceito no perfil de 16 GB.
- O UltraShape validado libera steps 12–50, seed, `low_vram`, latentes, chunk, octree e escala conforme o script oficial. Sem calibração, esses controles permanecem bloqueados.
- **Dividir**, **simplificar**, **remesh** e **transformar** usam o GLB aberto, criam um job filho e mantêm o GLB pai. O limite nunca subdivide e só aceita resultado até 1% acima do teto. O remesh é aceito somente quando preserva os atributos PBR auditados; retexture continua indisponível enquanto não houver um worker de rebake PBR real.

## Arquivos de suporte

- `runtime/engine-profile.json`: perfil, qualidades reais e status da calibração.
- `runtime/ultrashape-probe.json`: relatório do worker UltraShape.
- `backend/data/jobs/<id>/manifest.json`: ferramentas, tempos, fallback, artefatos e auditoria do job.
- `logs/`: logs do backend, interface e trellis.cpp.

## Referências e licença

- [trellis.cpp](https://github.com/pwilkin/trellis.cpp) fornece o runtime local usado pelo Forge3D.
- [UltraShape 1.0](https://github.com/PKU-YuanGroup/UltraShape-1.0) é usado apenas para refinamento geométrico opcional.

Leia a licença dos pesos e do código antes de distribuir modelos ou instalar o stack em ambiente comercial. A disponibilidade técnica não altera essas obrigações.
