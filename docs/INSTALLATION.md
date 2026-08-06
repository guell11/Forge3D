# Instalação Forge3D

Execute apenas um perfil base em `instalação/`: `bat-low-vram-6gb.bat`, `bat-8gb-vram.bat`, `bat-12gb-vram.bat` ou `bat-16gb-vram.bat`. O instalador baixa o runtime trellis.cpp, os conjuntos GGUF publicados e as dependências da API. Arquivos grandes são gravados primeiro como `.part`; execute novamente o mesmo instalador ou `repair-install.bat` para retomar.

Os perfis 6/8 GB baixam `q4`. Os perfis 12/16 GB baixam `q4` e `q8`, mas iniciam com Q4 como diretório seguro padrão. A lista de tiers e os arquivos realmente presentes são registrados em `runtime/engine-profile.json` somente depois do preflight da API, runtime e pesos TRELLIS.

`install-ultrashape-native-experimental.bat` é opcional e separado. Ele exige Windows, Python 3.10, NVIDIA/CUDA, Git e Build Tools quando alguma dependência precisar compilar; fixa PyTorch 2.5.1/cu121 e usa o repositório upstream, sem injetar flags CUDA 13 ou patches SDPA. Antes do download ele pede confirmação dos termos experimentais/licença. O script executa uma calibração de verdade. Se falhar ou os termos não forem confirmados, o perfil base segue disponível e o manifesto deixa UltraShape como indisponível.

`install-blender-4.5-lts-portable.bat` baixa Blender portátil 4.5.12, verifica SHA-256 e executa uma transformação real sobre um GLB pequeno. Só depois desse teste o worker de `split`, `simplify`, `remesh` e `transform` é registrado. O remesh usa a malha do GLB pai e é rejeitado se perder UV/textura auditada; `retexture` continua bloqueado enquanto não houver rebake PBR validado.

No Linux, use os equivalentes `.sh` para a instalação base e Blender portátil. O refinador UltraShape não é marcado como suportado pelo script Linux nesta versão.
