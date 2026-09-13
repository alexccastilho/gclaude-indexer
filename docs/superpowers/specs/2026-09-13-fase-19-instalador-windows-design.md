# Fase 19 — Instalador do Windows (design)

Documento de design escrito antes da implementação, em 2026-09-13, para a
versão 1.3.0. Descreve o estado do projeto no momento em que foi escrito e
não é editado depois para acompanhar mudanças posteriores — a mesma
convenção dos planos em `../plans/`.

## 1. O problema

Instalar hoje exige abrir o PowerShell dentro de uma pasta e executar um
script. Duas coisas param quem deveria estar usando o programa:

- **A barreira técnica.** Para quem não programa, "abra o PowerShell na
  pasta do projeto" já é o fim da tentativa.
- **A desconfiança do Windows.** Script não assinado baixado da internet
  faz o sistema e o antivírus reclamarem, e a pessoa desiste antes de
  instalar.

A fase entrega um instalador gráfico com desinstalador registrado no
Windows, modo silencioso, e publicação no winget.

## 2. O que já existe, e que não será reescrito

Esta é a decisão que governa todo o resto.

- `install.ps1` — 2.972 linhas. Instala Python 3.12 (baixando do
  python.org, com SHA-256 conferido, quando falta), Tesseract,
  Ghostscript, Ollama e o modelo padrão, instala as bibliotecas de sensor,
  ajusta o PATH pelo registro e cria atalhos. Aceita `-AutoInstall`,
  `-NoShortcut`, `-CpuSensorShortcut`, `-OcrLanguage` e `-SkipGpuCheck`.
- `uninstall.ps1` — 496 linhas, com `-RemoveAll`, `-KeepDependencies` e
  `-WhatIfOnly`.
- `Indexer.bat` — detecta ambiente virtual ausente e roda o `install.ps1`
  antes de subir o aplicativo.
- `install_diagnostics.py` — verifica o estado da instalação e reporta na
  interface.

**Verificado durante o design:** as seis chamadas de `Read-Host` do
`install.ps1` estão todas atrás de `if (-not $AutoInstall)`. O modo
automático é genuinamente não interativo, o que é pré-requisito do modo
silencioso.

**Verificado durante o design:** o aplicativo não escreve dentro da
própria pasta. Os dois usos de `app_root()` são leitura
(`config/classification_rules.json` e um diretório de trabalho); tudo o
que é gravado vai para `%LOCALAPPDATA%\GClaudeIndexer` ou para a pasta de
saída do projeto. Instalar em Arquivos de Programas, onde usuário comum
não escreve, é portanto viável sem refatoração.

## 3. Decisões tomadas com o usuário

| Questão | Decisão |
|---|---|
| Motivação | Usuário leigo travando no PowerShell **e** desconfiança do Windows |
| Assinatura de código | **Sem certificado.** winget como canal de confiança; executável não assinado no GitHub |
| Dependências | **Baixadas na instalação**, como hoje. Instalador pequeno |
| Destino | **O usuário escolhe** entre só para ele e para a máquina toda |
| Idiomas | Três, como todo o resto do projeto |

### 3.1 EULA e GPL-3.0

O pedido original falava em EULA. **Uma EULA no sentido usual é
incompatível com a GPL-3.0**: qualquer restrição adicional imposta ao
usuário invalida a licença sob a qual o software é distribuído. O que o
instalador exibe é uma **tela de aceite com o texto da própria GPL-3.0**,
que é o que instaladores de software livre fazem. Visualmente idêntico ao
que foi pedido; juridicamente o oposto.

### 3.2 Assinatura: o que a escolha custa

Sem assinatura, o executável baixado do GitHub dispara o aviso de tela
cheia do SmartScreen. Trocar script por executável **agrava** esse
problema no curto prazo, porque um `.exe` desconhecido assusta mais que um
`.zip` de scripts.

Fica registrado, para decisão futura: a SignPath Foundation oferece
assinatura de código sem custo para projetos de código aberto que atendam
critérios — licença aprovada pela OSI, repositório público, build
reproduzível a partir do fonte público. O projeto aparenta atender aos
três. Verificar elegibilidade é trabalho real e não faz parte desta fase.

### 3.3 Redistribuição

Como as dependências são baixadas e não embutidas, o projeto **não
redistribui binário de terceiros**. Isso dispensa o arquivo de avisos de
terceiros que a redistribuição exigiria.

## 4. Abordagem

Três foram consideradas.

**A — Inno Setup chamando o `install.ps1`.** ✅ **Escolhida.**

O instalador copia os arquivos, mostra as telas e invoca o script
existente para o trabalho de dependências. O Inno traz de fábrica: tela de
licença, seleção de idioma com traduções oficiais em pt-BR, es e en,
escolha entre por usuário e por máquina numa diretiva
(`PrivilegesRequiredOverridesAllowed=dialog`), registro em Programas e
Recursos, e modo silencioso.

O argumento decisivo é o canal: o winget conhece o tipo `inno`
nativamente, com chaves de silêncio conhecidas, o que remove uma categoria
de atrito na moderação.

**B — NSIS chamando o `install.ps1`.** Mesma estratégia, executável menor,
linguagem mais crua. A escolha entre por usuário e por máquina vira
trabalho manual, e as traduções da interface também. Defensável, sem
vantagem clara.

**C — MSI via WiX.** Descartada. É o formato que departamento de TI
espera, mas o caso corporativo não é o alvo, e MSI é hostil a baixar
centenas de megabytes durante a instalação — isso vira ação personalizada
chamando PowerShell, frágil e difícil de reverter corretamente.

## 5. Arquitetura

O instalador **não é um programa de instalação novo**. É uma casca em
volta de máquina que já funciona. A regra: se o `install.ps1` já sabe
fazer, o instalador chama; não reimplementa.

Restam três responsabilidades genuinamente novas.

**Identidade perante o Windows.** A entrada em Programas e Recursos —
nome, versão, editor, ícone, tamanho estimado, comando de desinstalação,
URL do repositório — em `HKCU` ou `HKLM` conforme o modo.

**Um rosto.** As telas do assistente.

**Um contrato com o winget.** Executar sem interação quando receber a
chave de silêncio, e devolver código de saída verdadeiro.

### 5.1 Os dois modos

- **Só para mim:** `%LOCALAPPDATA%\Programs\GClaude Indexer`, sem
  elevação, registro em `HKCU`.
- **Para todos:** Arquivos de Programas, uma elevação no início, registro
  em `HKLM`.

Nos dois casos o ambiente virtual, o catálogo e os logs continuam por
usuário em `%LOCALAPPDATA%`. O segundo usuário de uma instalação por
máquina monta o próprio ambiente no primeiro uso, porque o `Indexer.bat`
já detecta ambiente ausente e chama o `install.ps1`.

### 5.2 O que o instalador não faz

- Não baixa o modelo por padrão. São gigabytes; é opção desmarcada.
- Não toca em acervo nenhum, nem na desinstalação.
- Não substitui o `.zip`, que continua disponível.

## 6. Componentes

### 6.1 Novos, sob `installer/`

| Arquivo | Responsabilidade |
|---|---|
| `GClaudeIndexer.iss` | Script do Inno: telas, arquivos, ícones, registro, chamadas ao PowerShell, e as mensagens próprias nos três idiomas em `[CustomMessages]` |
| `build.ps1` | Compila chamando o `ISCC`; mesma entrada na máquina do autor e na CI |
| `winget/manifest.template.yaml` | Modelo do manifesto, preenchido com versão e hash na release |
| `sandbox/instalador.wsb` | Configuração do Windows Sandbox para teste manual em máquina limpa |
| `.github/workflows/installer.yml` | Compila e anexa o instalador à release |

### 6.2 Alterados

- **`install.ps1`** ganha `-StatusFile <caminho>`, lido pelo instalador
  para atualizar o rótulo da janela. Aditivo: quem roda à mão não vê
  diferença.

  O formato é um contrato entre dois componentes e fica definido aqui,
  não deixado para a implementação. O arquivo é **reescrito inteiro** a
  cada mudança de etapa, em UTF-8, com exatamente duas linhas:

  ```
  <etapa>|<total>|<chave>
  <texto para o usuário>
  ```

  A primeira linha é para a máquina: número da etapa corrente, número
  total de etapas, e uma chave estável em inglês (`python`, `venv`,
  `deps`, `tesseract`, `ghostscript`, `ollama`, `model`, `sensors`). A
  segunda é a prosa já traduzida, para exibir.

  Reescrever o arquivo inteiro, em vez de acrescentar linhas, evita que o
  instalador leia um arquivo pela metade enquanto o script escreve.
  Arquivo ausente ou ilegível significa "sem informação ainda", nunca
  erro: o progresso é cortesia, e falhar a instalação porque o rótulo não
  atualizou seria absurdo.
- **`uninstall.ps1`** ganha modo completamente não interativo. O
  desinstalador do Windows nunca pode abrir console pedindo resposta.

### 6.3 Uma fonte só para a versão

`SYSTEM_VERSION` vive em `web/app.py`. O `build.ps1` lê dali e passa ao
compilador por definição de linha de comando. Escrever a versão num
segundo lugar reintroduziria a classe de defeito que mordeu a fase 17 três
vezes: valor derivado em dois lugares por regras diferentes.

### 6.4 Atalhos pertencem ao instalador

O `install.ps1` é chamado com `-NoShortcut`, e os atalhos são criados pela
seção de ícones do Inno. Parece redundante e não é: atalho criado fora do
controle do instalador sobrevive à desinstalação como ícone órfão
apontando para pasta inexistente.

## 7. Fluxo

### 7.1 Instalação assistida

Idioma → boas-vindas → licença GPL-3.0 com aceite → modo → pasta →
opcionais → pronto → instalando → concluído.

Os opcionais são três caixas: **baixar o modelo agora** (com o tamanho ao
lado, **desmarcada**), atalho na área de trabalho, atalho do sensor de
CPU.

Na etapa de instalação: copiar arquivos, chamar
`install.ps1 -AutoInstall -NoShortcut -StatusFile <tmp>`, e atualizar o
rótulo a partir do arquivo de status.

### 7.2 Instalação silenciosa

Dois padrões que precisam estar certos:

- **Por usuário.** O winget roda sem elevação; exigir administrador
  dispararia UAC no meio de algo que deveria ser silencioso.
- **Sem o modelo.** Baixar gigabytes sem pedido explícito é hostil.

Código de saída zero apenas quando o aplicativo ficou utilizável (ver §8).

### 7.3 Atualização

Instalar por cima é reconhecido pelo identificador e vira atualização no
lugar. O `install.ps1` roda de novo, o que é barato porque ele só
reinstala dependências quando o hash do `requirements.txt` mudou.
Ambiente, catálogo e acervos não são tocados.

### 7.4 Desinstalação

Uma página com uma pergunta: **remover também as dependências baixadas**
(Tesseract, Ghostscript, Ollama, Python 3.12), **desmarcada por padrão**,
porque outro programa pode depender delas.

A mesma página **afirma em texto que os acervos indexados não serão
apagados**. Quem desinstala um indexador tem exatamente esse medo, e o
silêncio aqui é o que faz a pessoa não desinstalar. A desinstalação
silenciosa preserva as dependências.

### 7.5 Quem já usa pelo zip

Vai acabar com duas cópias do código. Ambiente e catálogo são adotados
sozinhos, porque estão em `%LOCALAPPDATA%` e o script é idempotente; a
pasta antiga fica para trás. A tela final menciona isso, com o caminho
quando for detectável.

## 8. Tratamento de erro

**O erro mais perigoso é o instalador mentir que deu certo.** Hoje o
`install.ps1` avisa e continua quando um download falha — decisão certa
para um script observado por alguém, e desastrosa em silêncio, onde vira
código de saída zero com instalação quebrada.

A separação:

- **Essencial:** Python 3.12, ambiente virtual, dependências do
  `requirements.txt`. Falha aqui é código de saída diferente de zero,
  sempre.
- **Degradável:** Tesseract e Ghostscript (sem eles não há OCR, mas PDF
  com texto funciona); Ollama e o modelo (o aplicativo já cai para o motor
  de regras sozinho, com explicação na tela).

Falha em item degradável conclui com sucesso e registra o que faltou.
`install_diagnostics.py` já existe e reporta na interface — o instalador
garante que ele encontre a verdade, não inventa um relatório novo.

**Nenhuma tentativa de desfazer instalação de terceiro.** O Inno desfaz a
cópia de arquivos; Tesseract instalado e PATH alterado ficam. Remover um
Ghostscript que outro programa passou a usar é estrago pior do que
deixar. O instalador informa o que conseguiu e o que não.

**Elevação recusada** devolve à tela de escolha, não a uma falha, e nada
pode ter sido escrito em `HKLM` antes desse ponto.

**Cancelar** é honrado entre etapas, não no meio de uma transferência, e o
botão diz isso. Cancelar deixa o aplicativo no estado degradado alcançado.

**O aviso do SmartScreen** não tem como ser evitado sem assinatura. A
mitigação é avisar antes: a página de download e o README dizem o que vai
aparecer, por quê, e que o winget não passa por isso.

## 9. Testes

**O caminho silencioso vai para a CI**, em `windows-latest`: instalar em
silêncio, conferir código de saída, verificar arquivos, entrada de
registro e ambiente virtual; desinstalar em silêncio e verificar que tudo
saiu. A CI não julga a aparência, mas garante o comando que o winget
executa.

**O teste que protege o usuário também é automatizável:** criar uma pasta
de acervo falsa com os quatro Markdown, desinstalar, afirmar que continua
lá.

**A interface vai para o Windows Sandbox**, que o Windows 11 Pro já traz.
Máquina limpa e descartável, sem Python, sem Tesseract, sem nada — o
cenário que mais importa e o mais difícil de reproduzir numa máquina de
trabalho. Um arquivo de configuração no repositório monta a pasta do
instalador dentro dela.

**A matriz manual:** dois modos × (instalação nova, atualização,
desinstalação) × (com e sem modelo). Com roteiro escrito, meia hora por
release.

**As partes puras vão para teste normal:** extração da versão a partir do
`app.py`, geração do manifesto, e o contrato do `-StatusFile`.

## 10. Critério de aceitação

1. Instalação silenciosa numa máquina limpa termina com código zero e o
   aplicativo abre.
2. Instalação silenciosa com um download essencial falhando termina com
   código diferente de zero.
3. Instalação silenciosa com Tesseract indisponível termina com código
   zero, e o diagnóstico na interface aponta a ausência.
4. A entrada em Programas e Recursos aparece com nome, versão, editor e
   ícone, e o botão de desinstalar funciona.
5. Desinstalar não apaga acervo nenhum, e a tela diz isso antes.
6. Os dois modos de instalação funcionam de ponta a ponta, incluindo
   desinstalação.
7. Atualizar por cima preserva ambiente, catálogo e acervos.
8. Nenhum atalho órfão sobrevive à desinstalação.
9. O manifesto do winget é gerado com a versão e o hash corretos da
   release.
10. O instalador apresenta as três línguas.
