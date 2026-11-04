# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Gera o acervo de demonstração e o seu gabarito (fase 37).

Tudo aqui é inventado: o município "Vila Nova do Amparo", as pessoas, a
construtora, o CNPJ (dígitos verificadores inválidos de propósito) e o
número do processo. Nenhum texto foi copiado de documento real. O assunto é
um só, para que o acervo se leia como um processo de verdade: a licitação e
a reforma da Escola Municipal Professora Aurora Lima, de janeiro a agosto
de 2026, em dois volumes encadernados mais uma pasta de avulsos.

`PECAS` é a única fonte: dela saem os arquivos de `acervo/` e as linhas de
`gabarito.csv`. Quem muda uma peça regenera os dois com

    python demo/gerar_acervo.py

e NÃO roda o gerador à toa: o PyMuPDF grava um `/ID` novo a cada gravação,
e um PDF regravado sem mudança de texto aparece como alterado no git. O
teste `test_gerador_reproduz_o_acervo_versionado` compara o texto das
páginas, não os bytes, por esse motivo.

Limites que o programa impõe e o gerador respeita:

- `extraction._extract_file_pages` corta cada página em `chars_per_page`
  (2000) caracteres, e o texto convertido de .docx, .xlsx, .eml e imagem
  vira UMA página lógica. Toda página aqui fica abaixo de 1800 caracteres,
  para que nada seja cortado e o gabarito conte páginas como o programa.
- A digitalização é um ofício renderizado a 150 dpi em PNG de tons de
  cinza: legível pelo Tesseract (o 300 dpi dobraria o tamanho sem ganho
  para um texto de 10 pt) e sem camada de texto, como um scanner produz.
- Fontes base-14 do PDF (Helvetica), que cobrem o Latin-1 do português;
  travessão e aspas tipográficas ficam de fora porque não existem nelas.
"""

from __future__ import annotations

import csv
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

# --- Identidade fictícia ------------------------------------------------

# Conferido contra a lista completa de municípios do IBGE (5 571 nomes):
# não existe. O nome anterior era o de um município real do Rio
# Grande do Sul (IBGE 4323457) — a revisão da fase 37 pegou.
MUNICIPIO = "Vila Nova do Amparo"
PREFEITURA = f"Prefeitura Municipal de {MUNICIPIO}"
PROCESSO = "2026-0001/SME"
ESCOLA = "Escola Municipal Professora Aurora Lima"
CONSTRUTORA = "Construtora Horizonte Azul Ltda."
CNPJ_CONSTRUTORA = "00.000.000/0001-00"  # dígitos verificadores inválidos de propósito
CONCORRENTE = "Edificações Serra Verde Ltda."
CNPJ_CONCORRENTE = "11.111.111/0001-11"  # idem

PREFEITO = ("Carlos Nunes", "Prefeito Municipal")
SEC_EDUCACAO = ("Maria Souza", "Secretária Municipal de Educação")
SEC_OBRAS = ("Lúcia Martins", "Secretária Municipal de Obras")
PROCURADORA = ("Ana Lima", "Procuradora-Geral do Município")
PRESIDENTE_CPL = ("João Pereira", "Presidente da Comissão Permanente de Licitação")
FISCAL = ("Paulo Ramos", "Engenheiro Civil, fiscal do contrato")
CONTROLADOR = ("Pedro Alves", "Controlador-Geral do Município")
PROTOCOLO = ("Rita Campos", "Chefe do Setor de Protocolo Geral")
SOCIA = ("Beatriz Costa", "Sócia-administradora da " + CONSTRUTORA)
REPRESENTANTE = ("Marcos Teixeira", "Representante legal da " + CONCORRENTE)

_MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def _extenso(iso: str) -> str:
    """'2026-01-10' -> '10 de janeiro de 2026' (padrão de data do motor de regras)."""
    d = dt.date.fromisoformat(iso)
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


def _local_data(iso: str) -> str:
    return f"{MUNICIPIO}, {_extenso(iso)}."


def _assina(pessoa: tuple[str, str], marcador: str = "") -> str:
    nome, cargo = pessoa
    return (f"{marcador}\n\n" if marcador else "\n") + f"{nome}\n{cargo}"


@dataclass(frozen=True)
class Peca:
    arquivo: str              # relativo a acervo/
    tipo: str                 # vocabulário de config/classification_rules.json, ou ""
    data: str                 # ISO, ou ""
    autor: str                # texto livre, ou ""
    paginas: tuple[str, ...]  # texto de cada página; a primeira começa pelo título


# --- Volume 1: da autuação à homologação ----------------------------------

V1 = "Processo 2026-0001/volume_1.pdf"
V2 = "Processo 2026-0001/volume_2.pdf"
CONTRATO_PDF = "Contratos/contrato_reforma_escola.pdf"


def _volume_1() -> list[Peca]:
    pecas: list[Peca] = []

    pecas.append(Peca(V1, "TERMO", "2026-01-05", PROTOCOLO[0], (
        "TERMO DE AUTUAÇÃO\n\n"
        f"Aos cinco dias do mês de janeiro de 2026, autuo e registro sob o nº {PROCESSO} os documentos "
        f"que seguem, referentes à reforma geral da {ESCOLA}, encaminhados pela Secretaria Municipal de "
        "Educação.\n\n"
        "Interessado: Secretaria Municipal de Educação.\n"
        "Assunto: Contratação de empresa especializada para reforma geral do prédio escolar, com "
        "substituição da cobertura, revisão das instalações elétricas e hidráulicas, adequação de "
        "acessibilidade e pintura.\n\n"
        "As folhas deste volume são numeradas e rubricadas em sequência. Para constar, lavrei o presente "
        "termo.\n\n" + _local_data("2026-01-05") + _assina(PROTOCOLO),
    )))

    pecas.append(Peca(V1, "OFÍCIO", "2026-01-10", SEC_EDUCACAO[0], (
        "OFÍCIO Nº 12/2026 - SME\n\n" + _local_data("2026-01-10") + "\n\n"
        f"Ao Excelentíssimo Senhor\n{PREFEITO[0]}\n{PREFEITO[1]}\n\n"
        f"Assunto: Solicitação de abertura de processo licitatório para reforma da {ESCOLA}.\n\n"
        "Senhor Prefeito,\n\n"
        f"1. A {ESCOLA}, que atende 412 alunos do ensino fundamental em dois turnos, apresenta "
        "infiltrações na cobertura de três blocos, fiação exposta no bloco administrativo e banheiros "
        "sem adequação de acessibilidade, conforme a vistoria da Secretaria Municipal de Obras realizada "
        "em dezembro de 2025.\n\n"
        "2. Os reparos pontuais feitos nos últimos dois anos não resolveram o problema de origem: a "
        "estrutura de madeira do telhado está comprometida e as calhas não dão vazão às chuvas de "
        "verão. Em 18 de dezembro, duas salas do bloco B ficaram interditadas por um dia.\n\n"
        "3. Diante disso, solicito a Vossa Excelência autorização para a abertura de processo "
        "licitatório destinado à contratação de empresa especializada para a reforma geral do prédio, "
        "com o escopo abaixo:",
        "a) substituição integral da cobertura dos blocos A, B e C, com estrutura metálica e telhas "
        "termoacústicas;\n"
        "b) revisão completa das instalações elétricas, com novo quadro geral e circuitos independentes "
        "por bloco;\n"
        "c) reforma dos quatro conjuntos de banheiros, com um sanitário acessível por bloco;\n"
        "d) rampas e corrimãos nos acessos ao pátio e à quadra;\n"
        "e) pintura interna e externa.\n\n"
        "4. A estimativa preliminar da Secretaria de Obras é de R$ 486.320,00, com recursos do Fundo "
        "Municipal de Educação, dotação 12.361.0015.2.044, já prevista na lei orçamentária de 2026.\n\n"
        "5. Peço que, autorizada a despesa, o processo seja encaminhado à Secretaria de Obras para a "
        "elaboração do termo de referência e, em seguida, à Procuradoria-Geral para parecer.\n\n"
        "Atenciosamente," + _assina(SEC_EDUCACAO),
    )))

    pecas.append(Peca(V1, "", "2026-01-14", "", (
        f"Reunião de alinhamento - reforma da {ESCOLA}\n\n"
        "Data: 14/01/2026, às 9h.\nLocal: sala de reuniões da Secretaria Municipal de Educação.\n"
        "Pauta: escopo da reforma, prazo de execução durante o ano letivo e fonte de recursos.\n\n"
        "LISTA DE PRESENÇA\n\n"
        "Nome                          Órgão / função                          Assinatura\n"
        "Maria Souza                   SME - Secretária                         (assinado)\n"
        "Lúcia Martins                 SMO - Secretária                         (assinado)\n"
        "Paulo Ramos                   SMO - Engenheiro civil                   (assinado)\n"
        "Helena Prado                  EM Prof. Aurora Lima - Diretora          (assinado)\n"
        "Rogério Dias                  SME - Coordenador administrativo         (assinado)\n"
        "Pedro Alves                   Controladoria-Geral                      (assinado)\n\n"
        "Encaminhamentos: a SMO entrega a descrição do estado atual do prédio até 23/01; a direção da "
        "escola levanta a possibilidade de uso do turno da tarde no bloco C durante as obras; a "
        "Controladoria acompanha a instrução do processo.",
    )))

    pecas.append(Peca(V1, "MEMORANDO", "2026-01-20", SEC_OBRAS[0], (
        "MEMORANDO Nº 4/2026 - SMO\n\n" + _local_data("2026-01-20") + "\n\n"
        f"De: Secretaria Municipal de Obras\nPara: Secretaria Municipal de Educação\n\n"
        f"Assunto: Encaminhamento da descrição técnica do estado atual da {ESCOLA}.\n\n"
        "Senhora Secretária,\n\n"
        "Encaminho a descrição técnica do estado atual do prédio escolar, elaborada pelo engenheiro "
        "Paulo Ramos após as vistorias de 8, 9 e 15 de janeiro, para instruir o pedido de reforma "
        f"registrado no processo {PROCESSO}.\n\n"
        "A descrição confirma a necessidade de substituição da cobertura dos três blocos e aponta um "
        "item não previsto no ofício inicial: o reservatório superior de água, de fibrocimento, com "
        "trincas visíveis, que recomendo incluir no escopo.\n\n"
        "A estimativa de custo foi revista para R$ 486.320,00 com o reservatório incluído, dentro do "
        "valor informado à Prefeitura.\n\n"
        "Fico à disposição para os ajustes do termo de referência." + _assina(SEC_OBRAS, "Atenciosamente,"),
    )))

    pecas.append(Peca(V1, "", "2026-01-22", FISCAL[0], (
        f"Descrição do estado atual do prédio - {ESCOLA}\n\n"
        "Vistorias realizadas em 8, 9 e 15 de janeiro de 2026. Área construída: 2.140 m² em três "
        "blocos térreos (A: administração e 4 salas; B: 8 salas; C: refeitório, biblioteca e 2 salas), "
        "pátio coberto e quadra descoberta. Construção original de 1994, ampliação do bloco C em 2008.\n\n"
        "1. Cobertura\n"
        "Estrutura de madeira com peças atacadas por cupim nos blocos A e B; telhas de fibrocimento "
        "com trincas e remendos; calhas de chapa subdimensionadas e sem rufos. Infiltração ativa em "
        "6 das 14 salas, com forro de PVC deformado em 3 delas. Recomendação: substituição integral "
        "por estrutura metálica e telhas termoacústicas, com calhas e rufos novos.\n\n"
        "2. Reservatório superior\n"
        "Caixa de fibrocimento de 10 mil litros sobre o bloco A, com trincas longitudinais e sem "
        "tampa. Recomendação: substituição por reservatório de polietileno de 15 mil litros, com "
        "base nova.",
        "3. Instalações elétricas\n"
        "Quadro geral original, sem dispositivo DR, com disjuntores de fabricantes diversos e "
        "circuitos não identificados. Fiação exposta no corredor do bloco A e nas salas 7 e 8. "
        "Tomadas insuficientes para os equipamentos da sala de informática, ligadas por extensões. "
        "Recomendação: quadro geral novo com DR, quadros de distribuição por bloco, circuitos "
        "dedicados para informática e cozinha, e SPDA.\n\n"
        "4. Instalações hidrossanitárias\n"
        "Quatro conjuntos de banheiros, nenhum acessível. Louças e metais com vazamentos; ralos sem "
        "sifão; esgoto do bloco C com retorno em dias de chuva. Recomendação: reforma completa dos "
        "quatro conjuntos, um sanitário acessível por bloco, revisão da rede de esgoto do bloco C.\n\n"
        "5. Acessibilidade\n"
        "Desnível de 32 cm entre o pátio e o bloco C, vencido por degraus. Portas de 70 cm nas "
        "salas 1 a 4. Recomendação: rampa com corrimão duplo, alargamento de portas para 90 cm e "
        "piso tátil nas circulações.",
        "6. Pintura e esquadrias\n"
        "Pintura externa descascada em 70% da fachada; pintura interna com mofo nas salas com "
        "infiltração. Esquadrias de ferro com corrosão nos caixilhos do bloco B. Recomendação: "
        "tratamento das esquadrias, pintura interna e externa com tinta acrílica.\n\n"
        "7. Conclusão\n"
        "O prédio não oferece risco estrutural imediato, mas a cobertura e a rede elétrica exigem "
        "intervenção antes do período de chuvas de 2026/2027. Prazo de execução estimado: 150 dias, "
        "com a obra organizada por blocos para manter as aulas em dois deles. Custo estimado, com "
        "BDI de 24%: R$ 486.320,00.\n\n"
        + _local_data("2026-01-22") + "\n\n"
        "Paulo Ramos\nEngenheiro Civil - Secretaria Municipal de Obras\nRegistro profissional nº 000000-0 (fictício)",
    )))

    pecas.append(Peca(V1, "TERMO", "2026-02-02", "Secretaria Municipal de Educação (SME)", (
        "TERMO DE REFERÊNCIA\n\n"
        f"Processo nº {PROCESSO}\nÓrgão requisitante: Secretaria Municipal de Educação\n\n"
        "1. OBJETO\n"
        f"Contratação de empresa especializada para a reforma geral da {ESCOLA}, compreendendo a "
        "substituição da cobertura dos blocos A, B e C, a substituição do reservatório superior, a "
        "revisão das instalações elétricas e hidrossanitárias, a adequação de acessibilidade e a "
        "pintura interna e externa, conforme projetos, memorial descritivo e planilha orçamentária "
        "anexos.\n\n"
        "2. JUSTIFICATIVA\n"
        "A escola atende 412 alunos e apresenta infiltrações, fiação exposta e ausência de sanitários "
        "acessíveis, conforme a descrição técnica da Secretaria Municipal de Obras de 22 de janeiro de "
        "2026. A reforma é condição para a manutenção das aulas no período de chuvas e para o "
        "cumprimento das normas de acessibilidade em edificações de uso público.",
        "3. ESPECIFICAÇÕES TÉCNICAS\n"
        "3.1 Cobertura: estrutura metálica em perfis galvanizados, telhas termoacústicas de 30 mm, "
        "calhas e rufos em chapa galvanizada nº 24, com projeto executivo a cargo da contratada.\n"
        "3.2 Reservatório: polietileno, 15 mil litros, base em concreto armado, com boia e extravasor.\n"
        "3.3 Elétrica: quadro geral com DR de 30 mA, quadros por bloco, circuitos independentes para "
        "informática e cozinha, SPDA conforme norma, luminárias LED em todas as salas.\n"
        "3.4 Hidrossanitário: reforma dos quatro conjuntos de banheiros, um sanitário acessível por "
        "bloco, revisão da rede de esgoto do bloco C com caixas de inspeção novas.\n"
        "3.5 Acessibilidade: rampa de 8,33% com corrimão duplo entre pátio e bloco C, portas de 90 cm "
        "nas salas 1 a 4, piso tátil direcional e de alerta nas circulações.\n"
        "3.6 Pintura: tratamento das esquadrias de ferro, massa e tinta acrílica em paredes internas e "
        "externas, duas demãos.",
        "4. PRAZO E REGIME DE EXECUÇÃO\n"
        "Prazo de execução: 150 dias corridos a partir da ordem de início, em três etapas por bloco, "
        "de modo que dois blocos permaneçam em uso durante toda a obra. Regime de empreitada por "
        "preço global.\n\n"
        "5. VALOR ESTIMADO E DOTAÇÃO\n"
        "Valor estimado: R$ 486.320,00 (quatrocentos e oitenta e seis mil, trezentos e vinte reais), "
        "conforme planilha orçamentária com BDI de 24%. Dotação: 12.361.0015.2.044 - Fundo Municipal de "
        "Educação, elemento 4.4.90.51.\n\n"
        "6. PAGAMENTO\n"
        "Medições mensais conferidas pela fiscalização, com pagamento em até 30 dias da apresentação "
        "da nota fiscal atestada e da comprovação de regularidade fiscal e trabalhista.",
        "7. FISCALIZAÇÃO\n"
        "A fiscalização será exercida por servidor designado por portaria, com registro em diário de "
        "obra, poderes para suspender serviços em desacordo com o projeto e dever de atestar as "
        "medições.\n\n"
        "8. GARANTIA\n"
        "Garantia de execução de 5% do valor do contrato, em uma das modalidades admitidas, e "
        "garantia dos serviços de 5 anos para a cobertura e de 1 ano para os demais itens.\n\n"
        "9. OBRIGAÇÕES DA CONTRATADA\n"
        "Manter engenheiro responsável em tempo parcial na obra, cumprir as normas de segurança do "
        "trabalho, isolar as áreas em execução do convívio dos alunos e recolher o entulho em caçambas "
        "licenciadas.\n\n"
        + _local_data("2026-02-02") + "\n\nSecretaria Municipal de Educação (SME)\nMaria Souza - Secretária Municipal",
    )))

    pecas.append(Peca(V1, "DESPACHO", "2026-02-05", PREFEITO[0], (
        "DESPACHO\n\n"
        f"Processo nº {PROCESSO}\n\n"
        f"1. Autorizo a abertura de procedimento licitatório para a reforma geral da {ESCOLA}, nos "
        "termos do Ofício nº 12/2026 - SME e do Termo de Referência de 2 de fevereiro de 2026, e "
        "declaro a adequação da despesa, estimada em R$ 486.320,00, ao orçamento de 2026.\n\n"
        "2. Encaminhe-se à Procuradoria-Geral do Município para parecer sobre a minuta de edital e de "
        "contrato, e em seguida à Comissão Permanente de Licitação para as providências de praxe.\n\n"
        + _local_data("2026-02-05") + _assina(PREFEITO),
    )))

    pecas.append(Peca(V1, "PARECER", "2026-02-12", "Procuradoria-Geral do Município (PGM)", (
        "PARECER JURÍDICO Nº 7/2026 - PGM\n\n"
        f"Processo nº {PROCESSO}\nInteressado: Secretaria Municipal de Educação\n\n"
        f"Ementa: Licitação. Obra de reforma da {ESCOLA}. Análise da minuta de edital e de contrato. "
        "Requisitos de instrução atendidos. Ajustes pontuais na minuta. Parecer favorável.\n\n"
        "I - RELATÓRIO\n"
        "Trata-se de consulta formulada pelo Senhor Prefeito, por despacho de 5 de fevereiro de 2026, "
        "sobre a regularidade da minuta de edital e de contrato para a contratação de empresa "
        "especializada na reforma geral do prédio escolar. O processo veio instruído com o ofício de "
        "solicitação, a descrição técnica do estado do prédio, o termo de referência, a planilha "
        "orçamentária, a declaração de adequação orçamentária e a minuta do edital.",
        "II - FUNDAMENTAÇÃO\n"
        "A instrução contém os elementos que a legislação de licitações exige para obras: a "
        "justificativa da contratação, o projeto básico com memorial e planilha, a estimativa de custo "
        "com BDI explicitado, a indicação da dotação e a autorização da autoridade competente.\n\n"
        "A modalidade escolhida é compatível com o valor estimado e com o objeto. O critério de "
        "julgamento por menor preço global é adequado a obra de escopo definido em projeto básico.\n\n"
        "Recomendo, na minuta de edital: (a) explicitar no item 7.3 que a certidão de regularidade "
        "trabalhista deve estar válida na data da sessão, e não apenas na data de sua emissão; (b) "
        "prever visita técnica facultativa, com declaração de conhecimento do local em substituição; "
        "(c) fixar o prazo recursal em dias úteis, contado da intimação do resultado.\n\n"
        "Na minuta de contrato, recomendo incluir cláusula expressa sobre a organização da obra por "
        "blocos, de forma a vincular a contratada ao funcionamento parcial da escola.",
        "III - CONCLUSÃO\n"
        "Com os ajustes indicados, a minuta de edital e a de contrato atendem à legislação aplicável, "
        "e o processo está apto a prosseguir para a publicação do edital.\n\n"
        "É o parecer, que submeto à consideração superior.\n\n"
        + _local_data("2026-02-12") + "\n\nAna Lima\nProcuradora-Geral do Município\nProcuradoria-Geral do Município (PGM)",
    )))

    pecas.append(Peca(V1, "PORTARIA", "2026-02-16", PREFEITO[0], (
        "PORTARIA Nº 55/2026\n\n"
        "Designa a Comissão Permanente de Licitação para o exercício de 2026 e dá outras providências.\n\n"
        f"O PREFEITO MUNICIPAL DE {MUNICIPIO.upper()}, no uso das atribuições que lhe confere a Lei "
        "Orgânica do Município,\n\n"
        "RESOLVE:\n\n"
        "Art. 1º Designar, para compor a Comissão Permanente de Licitação no exercício de 2026, os "
        "servidores João Pereira, presidente; Fernanda Rocha, membro; e Tiago Moreira, membro, tendo "
        "como suplente Rogério Dias.\n\n"
        "Art. 2º A comissão conduzirá os certames de obras e serviços de engenharia, inclusive o "
        f"referente ao processo nº {PROCESSO}, e responderá pelas sessões públicas, pelo julgamento das "
        "propostas e pela instrução dos recursos.\n\n"
        "Art. 3º Esta portaria entra em vigor na data de sua publicação.\n\n"
        + _local_data("2026-02-16") + _assina(PREFEITO),
    )))

    pecas.append(Peca(V1, "EDITAL", "2026-02-20", "Comissão Permanente de Licitação (CPL)", (
        "EDITAL DE LICITAÇÃO Nº 3/2026\n\n"
        f"Processo nº {PROCESSO}\nModalidade: concorrência\nCritério de julgamento: menor preço global\n"
        "Regime de execução: empreitada por preço global\n\n"
        f"A {PREFEITURA}, por meio da Comissão Permanente de Licitação designada pela Portaria nº "
        "55/2026, torna público que realizará licitação para a contratação de empresa especializada "
        f"na reforma geral da {ESCOLA}, conforme as condições deste edital e de seus anexos.\n\n"
        "Sessão pública de abertura: 12 de março de 2026, às 9h, na sala de licitações da Prefeitura, "
        "Rua das Palmeiras, 100, Centro.\n\n"
        "1. DO OBJETO\n"
        "1.1 Reforma geral do prédio escolar, com substituição da cobertura, do reservatório superior, "
        "revisão das instalações elétricas e hidrossanitárias, adequação de acessibilidade e pintura, "
        "conforme o Termo de Referência (Anexo I), o memorial descritivo (Anexo II) e a planilha "
        "orçamentária (Anexo III).\n"
        "1.2 Valor estimado: R$ 486.320,00. Prazo de execução: 150 dias corridos.",
        "2. DAS CONDIÇÕES DE PARTICIPAÇÃO\n"
        "2.1 Poderão participar empresas do ramo de construção civil, legalmente constituídas, que "
        "atendam às exigências de habilitação deste edital.\n"
        "2.2 Não poderão participar empresas suspensas de licitar com o Município, declaradas "
        "inidôneas, em recuperação judicial sem plano homologado, ou cujos sócios sejam servidores do "
        "Município.\n"
        "2.3 A visita técnica é facultativa e poderá ser agendada com a Secretaria de Obras até 10 de "
        "março de 2026. A licitante que não a realizar apresentará declaração de pleno conhecimento "
        "das condições do local.\n\n"
        "3. DO CREDENCIAMENTO\n"
        "3.1 Na sessão pública, o representante apresentará documento de identidade e instrumento que "
        "lhe confira poderes para praticar todos os atos do certame.\n"
        "3.2 Cada licitante terá um único representante credenciado.",
        "4. DA PROPOSTA DE PREÇOS (ENVELOPE 1)\n"
        "4.1 A proposta conterá preço global em reais, planilha de composição por item conforme o Anexo "
        "III, cronograma físico-financeiro, prazo de validade não inferior a 60 dias e declaração de que "
        "nos preços estão incluídos todos os custos diretos e indiretos.\n"
        "4.2 Será desclassificada a proposta com preço global superior ao estimado, com preço unitário "
        "superior ao da planilha de referência em item de maior relevância, ou manifestamente "
        "inexequível.\n\n"
        "5. DA HABILITAÇÃO (ENVELOPE 2)\n"
        "5.1 Habilitação jurídica: ato constitutivo e documento de identificação do representante.\n"
        "5.2 Regularidade fiscal e trabalhista: inscrição no CNPJ, certidões de regularidade com as "
        "Fazendas federal, estadual e municipal, com o FGTS e a certidão negativa de débitos "
        "trabalhistas.\n"
        "5.3 Qualificação técnica: registro da empresa e do responsável técnico no conselho "
        "profissional e atestado de execução de obra de reforma de edificação com área mínima de 1.000 m².\n"
        "5.4 Qualificação econômico-financeira: balanço do último exercício e certidão negativa de "
        "falência.",
        "6. DO PROCEDIMENTO DA SESSÃO\n"
        "6.1 Abertos os envelopes de proposta, a comissão classificará as propostas por ordem de preço "
        "global e, em seguida, abrirá o envelope de habilitação da primeira classificada.\n"
        "6.2 Inabilitada a primeira classificada, a comissão examinará a habilitação da seguinte, e "
        "assim sucessivamente, até encontrar licitante que atenda ao edital.\n"
        "6.3 Da sessão será lavrada ata circunstanciada, assinada pela comissão e pelos representantes "
        "presentes.\n\n"
        "7. DOS DOCUMENTOS E PRAZOS\n"
        "7.1 Os documentos poderão ser apresentados em original, por cópia autenticada ou por "
        "publicação em órgão oficial.\n"
        "7.2 As certidões sem prazo de validade expresso serão aceitas se emitidas até 90 dias antes da "
        "sessão.\n"
        "7.3 As certidões de regularidade fiscal e trabalhista devem estar válidas na data da sessão "
        "pública de abertura, e não apenas na data de sua emissão.",
        "8. DOS RECURSOS\n"
        "8.1 Das decisões da comissão cabe recurso no prazo de 5 dias úteis, contado da intimação do "
        "ato ou da lavratura da ata, dirigido à autoridade superior por intermédio da comissão.\n"
        "8.2 Interposto o recurso, as demais licitantes serão intimadas para contrarrazões em igual "
        "prazo.\n"
        "8.3 A comissão poderá reconsiderar a decisão em 5 dias úteis ou, mantendo-a, encaminhará o "
        "recurso à autoridade superior, que decidirá em igual prazo.\n\n"
        "9. DO CONTRATO\n"
        "9.1 A adjudicatária será convocada para assinar o contrato em 5 dias úteis, prorrogáveis uma "
        "vez por igual período, sob pena de perder o direito à contratação.\n"
        "9.2 O contrato terá vigência de 210 dias, com prazo de execução de 150 dias contado da ordem de "
        "início, e seguirá a minuta do Anexo IV.\n"
        "9.3 A obra será organizada por blocos, de modo que dois blocos permaneçam em uso durante toda a "
        "execução.",
        "10. DO PAGAMENTO E DO REAJUSTE\n"
        "10.1 Pagamento por medição mensal, em até 30 dias da apresentação da nota fiscal atestada pela "
        "fiscalização, acompanhada das certidões de regularidade.\n"
        "10.2 Os preços são fixos e irreajustáveis no prazo contratual original.\n\n"
        "11. DAS SANÇÕES\n"
        "11.1 O atraso injustificado sujeita a contratada a multa de 0,2% por dia sobre o valor da "
        "etapa em atraso, até o limite de 10%, sem prejuízo das demais sanções legais.\n\n"
        "12. DAS DISPOSIÇÕES FINAIS\n"
        "12.1 Esclarecimentos e impugnações serão recebidos até 3 dias úteis antes da sessão, pelo "
        "endereço licitacoes@vilanovadosul.exemplo, e respondidos a todas as interessadas.\n"
        "12.2 Integram este edital os Anexos I a IV.\n"
        "12.3 Fica eleito o foro da comarca para dirimir questões decorrentes deste edital.\n\n"
        + _local_data("2026-02-20") + "\n\nComissão Permanente de Licitação (CPL)\nJoão Pereira - Presidente",
    )))

    pecas.append(Peca(V1, "CERTIDÃO", "2026-02-23", PROTOCOLO[0], (
        "CERTIDÃO\n\n"
        f"Certifico, para os devidos fins, que o Edital de Licitação nº 3/2026, referente ao processo "
        f"nº {PROCESSO}, foi publicado na edição nº 1.203 do Diário Oficial do Município, de 23 de "
        "fevereiro de 2026, páginas 4 a 6, e afixado no quadro de avisos do átrio da Prefeitura na "
        "mesma data, observado o prazo mínimo entre a publicação e a sessão pública.\n\n"
        "Certifico ainda que o aviso resumido do edital foi encaminhado para publicação em jornal de "
        "circulação regional, conforme comprovante juntado em seguida.\n\n"
        "O referido é verdade e dou fé.\n\n"
        + _local_data("2026-02-23") + _assina(PROTOCOLO),
    )))

    pecas.append(Peca(V1, "", "2026-03-02", "", (
        "Impressão de mensagem eletrônica - juntada para registro\n\n"
        "De: comercial@serraverde.exemplo\n"
        "Para: licitacoes@vilanovadosul.exemplo\n"
        "Enviado em: 02/03/2026 10:42\n"
        "Assunto: Dúvida sobre o item 7.3 do Edital nº 3/2026\n\n"
        "Prezados,\n\n"
        "Nossa certidão negativa de débitos trabalhistas vence em 11/03/2026, um dia antes da sessão. "
        "Como o item 7.3 fala em validade na data da sessão, entendemos que precisamos emitir uma nova "
        "certidão antes do dia 12. Está correto o entendimento? Caso a nova certidão não fique pronta "
        "a tempo, a comissão aceitaria a certidão anterior com protocolo do pedido de renovação?\n\n"
        "Agradecemos a atenção.\n\n"
        "-----\n\n"
        "RASCUNHO DE RESPOSTA (não enviado):\n\n"
        "O entendimento está correto quanto à primeira parte: a certidão deve estar válida em 12/03. "
        "Quanto à segunda, o edital não prevê a aceitação de protocolo de renovação em lugar da "
        "certidão. Resposta a ser publicada a todas as interessadas até 06/03.",
    )))

    pecas.append(Peca(V1, "ATA", "2026-03-12", PRESIDENTE_CPL[0], (
        "ATA DA SESSÃO PÚBLICA\n\n"
        f"Edital de Licitação nº 3/2026 - Processo nº {PROCESSO}\n\n"
        "Aos doze dias do mês de março de 2026, às 9h, na sala de licitações da Prefeitura Municipal de "
        f"{MUNICIPIO}, reuniu-se a Comissão Permanente de Licitação, designada pela Portaria nº 55/2026, "
        "composta por João Pereira, presidente, Fernanda Rocha e Tiago Moreira, membros, para a sessão "
        f"pública de recebimento e abertura dos envelopes da licitação destinada à reforma geral da {ESCOLA}.\n\n"
        "1. Credenciamento\n"
        f"Compareceram e foram credenciadas duas licitantes: {CONSTRUTORA}, CNPJ {CNPJ_CONSTRUTORA}, "
        f"representada por Beatriz Costa; e {CONCORRENTE}, CNPJ {CNPJ_CONCORRENTE}, representada por "
        "Marcos Teixeira. Ambas apresentaram declaração de pleno conhecimento das condições do local.",
        "2. Abertura das propostas\n"
        "Abertos os envelopes nº 1, as propostas foram rubricadas pela comissão e pelos representantes "
        "e lidas em voz alta, com os seguintes preços globais:\n\n"
        f"{CONSTRUTORA} ............ R$ 462.900,00 - prazo 150 dias\n"
        f"{CONCORRENTE} ........... R$ 471.500,00 - prazo 140 dias\n\n"
        "Ambas as propostas apresentaram planilha de composição e cronograma físico-financeiro e "
        "ficaram abaixo do valor estimado, sendo classificadas na ordem acima.\n\n"
        "3. Habilitação\n"
        f"Aberto o envelope nº 2 da primeira classificada, {CONSTRUTORA}, a comissão verificou que todos "
        "os documentos exigidos nos itens 5.1 a 5.4 do edital foram apresentados e estão válidos, "
        "inclusive atestado de reforma de edificação escolar com 1.420 m², e declarou a licitante "
        "habilitada.",
        "4. Manifestações\n"
        f"O representante da {CONCORRENTE} registrou que a certidão negativa de débitos trabalhistas de "
        "sua empresa, juntada no envelope nº 2, venceu em 11 de março, e que a nova certidão, emitida "
        "nesta data, não pôde ser incluída no envelope lacrado. Pediu que a comissão a recebesse em "
        "sessão. A comissão indeferiu o pedido, por força do item 7.3 do edital e da resposta publicada "
        "em 6 de março, e esclareceu que o envelope da segunda classificada não foi aberto, por ter "
        "sido habilitada a primeira. O representante manifestou intenção de recorrer.\n\n"
        "5. Resultado\n"
        f"A comissão declarou vencedora a licitante {CONSTRUTORA}, pelo preço global de R$ 462.900,00, "
        "e abriu o prazo de 5 dias úteis para recurso, contado desta data.\n\n"
        "Nada mais havendo, a sessão foi encerrada às 11h20, e eu, Fernanda Rocha, lavrei a presente "
        "ata, que vai assinada pela comissão e pelos representantes presentes.\n\n"
        "João Pereira - Presidente\nFernanda Rocha - Membro\nTiago Moreira - Membro\n"
        "Beatriz Costa - representante\nMarcos Teixeira - representante",
    )))

    pecas.append(Peca(V1, "RECURSO", "2026-03-17", REPRESENTANTE[0], (
        "RECURSO ADMINISTRATIVO\n\n"
        f"À Comissão Permanente de Licitação da {PREFEITURA}\n"
        f"Ref.: Edital de Licitação nº 3/2026 - Processo nº {PROCESSO}\n\n"
        f"{CONCORRENTE}, inscrita no CNPJ sob o nº {CNPJ_CONCORRENTE}, por seu representante legal, "
        "vem, tempestivamente, apresentar RECURSO ADMINISTRATIVO contra a decisão que indeferiu a "
        "juntada de certidão em sessão e declarou vencedora a primeira classificada, pelas razões a "
        "seguir.\n\n"
        "I - DOS FATOS\n"
        "A recorrente apresentou, no envelope de habilitação, certidão negativa de débitos trabalhistas "
        "válida até 11 de março de 2026, véspera da sessão. Em 12 de março, antes da abertura dos "
        "envelopes, obteve nova certidão, igualmente negativa, e requereu sua juntada, o que foi "
        "indeferido pela comissão.",
        "II - DO DIREITO\n"
        "A finalidade da exigência de regularidade trabalhista é verificar que a licitante não possui "
        "débitos, situação que a nova certidão comprova e que a anterior nunca negou. O indeferimento "
        "privilegia a forma em prejuízo da finalidade do certame, que é a seleção da proposta mais "
        "vantajosa com o maior número de competidores.\n\n"
        "Ademais, a comissão sequer abriu o envelope de habilitação da recorrente, de modo que a "
        "decisão de não recebê-la antecipou um juízo sobre documento que não chegou a ser examinado "
        "no procedimento regular.\n\n"
        "A recorrente ofereceu proposta com prazo de execução menor, de 140 dias, o que, no caso de "
        "uma escola em funcionamento, representa vantagem concreta para a Administração e para os "
        "alunos.",
        "III - DO PEDIDO\n"
        "Diante do exposto, requer:\n"
        "a) o recebimento e o conhecimento deste recurso, com efeito suspensivo;\n"
        "b) a reconsideração da decisão, com o recebimento da certidão emitida em 12 de março de 2026 "
        "e a abertura do envelope de habilitação da recorrente;\n"
        "c) subsidiariamente, a anulação da sessão e a designação de nova data para a abertura dos "
        "envelopes de habilitação de ambas as licitantes.\n\n"
        "Nestes termos, pede deferimento.\n\n"
        + _local_data("2026-03-17") + "\n\n"
        f"Marcos Teixeira\nRepresentante legal\n{CONCORRENTE}",
    )))

    pecas.append(Peca(V1, "DECISÃO", "2026-03-25", PRESIDENTE_CPL[0], (
        "DECISÃO\n\n"
        f"Recurso administrativo - Edital de Licitação nº 3/2026 - Processo nº {PROCESSO}\n"
        f"Recorrente: {CONCORRENTE}\n\n"
        "1. A recorrente impugna o indeferimento da juntada, em sessão, de certidão negativa de débitos "
        "trabalhistas emitida no próprio dia da abertura dos envelopes, e pede a abertura de seu "
        "envelope de habilitação.\n\n"
        "2. O recurso é tempestivo e foi recebido com efeito suspensivo. A primeira classificada, "
        "intimada, apresentou contrarrazões em 23 de março, sustentando a correção da decisão.\n\n"
        "3. O item 7.3 do edital, incluído por recomendação da Procuradoria-Geral e esclarecido em "
        "resposta publicada a todas as interessadas em 6 de março, exige certidões válidas na data da "
        "sessão. A própria recorrente consultou a comissão sobre esse ponto em 2 de março e foi "
        "informada de que o edital não admite substituição posterior de documento do envelope lacrado.",
        "4. Admitir a juntada de documento após o encerramento do prazo de entrega dos envelopes "
        "quebraria a isonomia entre as licitantes, que se vincularam às mesmas regras. A certidão "
        "vencida não comprova a regularidade na data exigida, e a nova certidão não integrava o "
        "envelope.\n\n"
        "5. O envelope de habilitação da recorrente não foi aberto porque a primeira classificada foi "
        "habilitada, conforme o item 6.2 do edital; não houve, portanto, juízo antecipado sobre seu "
        "conteúdo. O menor prazo de execução não é critério de julgamento neste certame.\n\n"
        "6. Pelo exposto, a comissão, por unanimidade, NEGA PROVIMENTO ao recurso e mantém a decisão "
        f"que declarou vencedora a licitante {CONSTRUTORA}, encaminhando os autos à autoridade "
        "superior para homologação.\n\n"
        + _local_data("2026-03-25") + "\n\nJoão Pereira - Presidente\nFernanda Rocha - Membro\nTiago Moreira - Membro",
    )))

    pecas.append(Peca(V1, "DESPACHO", "2026-03-30", PREFEITO[0], (
        "DESPACHO DE HOMOLOGAÇÃO E ADJUDICAÇÃO\n\n"
        f"Processo nº {PROCESSO} - Edital de Licitação nº 3/2026\n\n"
        "1. Acolho a decisão da Comissão Permanente de Licitação de 25 de março de 2026, que negou "
        f"provimento ao recurso interposto por {CONCORRENTE}, pelos seus próprios fundamentos.\n\n"
        f"2. HOMOLOGO o procedimento licitatório e ADJUDICO o objeto à licitante {CONSTRUTORA}, CNPJ "
        f"{CNPJ_CONSTRUTORA}, pelo valor global de R$ 462.900,00 (quatrocentos e sessenta e dois mil e "
        "novecentos reais).\n\n"
        "3. Convoque-se a adjudicatária para a assinatura do contrato no prazo do item 9.1 do edital. "
        "Publique-se.\n\n"
        + _local_data("2026-03-30") + _assina(PREFEITO),
    )))

    pecas.append(Peca(V1, "TERMO", "2026-03-31", PROTOCOLO[0], (
        "TERMO DE ENCERRAMENTO DE VOLUME\n\n"
        f"Aos trinta e um dias do mês de março de 2026, encerro o volume 1 do processo nº {PROCESSO}, "
        "contendo 35 folhas numeradas e rubricadas, da folha 1 à folha 35, e abro o volume 2, que se "
        "inicia na folha 36.\n\n"
        "Para constar, lavrei o presente termo.\n\n"
        + _local_data("2026-03-31") + _assina(PROTOCOLO),
    )))
    return pecas


# --- Contrato: o mesmo texto no volume 2 e na pasta de avulsos --------------

def _contrato(arquivo: str) -> Peca:
    return Peca(arquivo, "TERMO", "2026-04-06", PREFEITO[0], (
        "TERMO DE CONTRATO Nº 9/2026\n\n"
        f"Contrato de empreitada por preço global que entre si celebram a {PREFEITURA} e a {CONSTRUTORA} "
        f"para a reforma geral da {ESCOLA}, decorrente do Edital de Licitação nº 3/2026, processo nº "
        f"{PROCESSO}.\n\n"
        f"CONTRATANTE: {PREFEITURA}, pessoa jurídica de direito público, com sede na Rua das Palmeiras, "
        f"100, Centro, neste ato representada pelo Prefeito Municipal, {PREFEITO[0]}.\n\n"
        f"CONTRATADA: {CONSTRUTORA}, inscrita no CNPJ sob o nº {CNPJ_CONSTRUTORA}, com sede na Avenida "
        "dos Ipês, 850, Distrito Industrial, neste ato representada por sua sócia-administradora, "
        "Beatriz Costa.\n\n"
        "CLÁUSULA PRIMEIRA - DO OBJETO\n"
        f"1.1 O objeto deste contrato é a reforma geral da {ESCOLA}, compreendendo a substituição da "
        "cobertura dos blocos A, B e C, a substituição do reservatório superior, a revisão das "
        "instalações elétricas e hidrossanitárias, a adequação de acessibilidade e a pintura interna e "
        "externa, conforme o Termo de Referência, o memorial descritivo, a planilha orçamentária e a "
        "proposta da contratada, que integram este instrumento.",
        "CLÁUSULA SEGUNDA - DO VALOR\n"
        "2.1 O valor global deste contrato é de R$ 462.900,00 (quatrocentos e sessenta e dois mil e "
        "novecentos reais), fixo e irreajustável no prazo contratual original.\n\n"
        "CLÁUSULA TERCEIRA - DA DOTAÇÃO\n"
        "3.1 As despesas correrão à conta da dotação 12.361.0015.2.044 - Fundo Municipal de Educação, "
        "elemento 4.4.90.51, do orçamento de 2026.\n\n"
        "CLÁUSULA QUARTA - DOS PRAZOS\n"
        "4.1 O prazo de execução é de 150 dias corridos, contado da ordem de início emitida pela "
        "Secretaria Municipal de Obras.\n"
        "4.2 A vigência do contrato é de 210 dias, contada da assinatura.\n"
        "4.3 Os prazos poderão ser prorrogados por fato superveniente devidamente justificado, "
        "mediante termo aditivo.\n\n"
        "CLÁUSULA QUINTA - DA EXECUÇÃO POR BLOCOS\n"
        "5.1 A obra será executada em três etapas, uma por bloco, na ordem B, A e C, de modo que dois "
        "blocos permaneçam em uso pela escola durante toda a execução, com as áreas de obra isoladas "
        "do convívio dos alunos por tapumes.",
        "CLÁUSULA SEXTA - DO PAGAMENTO\n"
        "6.1 O pagamento será feito por medição mensal, conferida e atestada pela fiscalização, em até "
        "30 dias da apresentação da nota fiscal, acompanhada das certidões de regularidade fiscal e "
        "trabalhista e da comprovação do recolhimento dos encargos da mão de obra do período.\n"
        "6.2 A primeira medição não poderá ultrapassar 30% do valor contratual.\n\n"
        "CLÁUSULA SÉTIMA - DA GARANTIA\n"
        "7.1 A contratada prestou garantia de execução de 5% do valor do contrato, na modalidade "
        "seguro-garantia, apólice nº 0000-FICTÍCIA, válida até o recebimento definitivo.\n"
        "7.2 A contratada garante os serviços de cobertura por 5 anos e os demais por 1 ano, contados "
        "do recebimento definitivo.\n\n"
        "CLÁUSULA OITAVA - DA FISCALIZAÇÃO\n"
        "8.1 A fiscalização será exercida por servidor designado por portaria, que manterá diário de "
        "obra, poderá suspender serviços em desacordo com o projeto e atestará as medições.",
        "CLÁUSULA NONA - DAS OBRIGAÇÕES DA CONTRATADA\n"
        "9.1 Executar a obra conforme o projeto e as normas técnicas, com engenheiro responsável em "
        "tempo parcial no canteiro.\n"
        "9.2 Cumprir as normas de segurança e saúde do trabalho e fornecer os equipamentos de proteção.\n"
        "9.3 Recolher o entulho em caçambas licenciadas e manter o canteiro limpo.\n"
        "9.4 Manter, durante toda a execução, as condições de habilitação exigidas na licitação.\n"
        "9.5 Reparar, às suas expensas, os vícios e defeitos verificados na execução.\n\n"
        "CLÁUSULA DÉCIMA - DAS OBRIGAÇÕES DA CONTRATANTE\n"
        "10.1 Emitir a ordem de início, disponibilizar o local da obra por blocos conforme a cláusula "
        "quinta, fiscalizar a execução e efetuar os pagamentos nos prazos ajustados.\n\n"
        "CLÁUSULA DÉCIMA PRIMEIRA - DAS SANÇÕES\n"
        "11.1 O atraso injustificado sujeita a contratada a multa de 0,2% por dia sobre o valor da etapa "
        "em atraso, até 10%, e a inexecução total ou parcial, às demais sanções previstas em lei, "
        "assegurados o contraditório e a ampla defesa.",
        "CLÁUSULA DÉCIMA SEGUNDA - DA RESCISÃO\n"
        "12.1 O contrato poderá ser rescindido nas hipóteses previstas em lei, com as consequências "
        "nela estabelecidas.\n\n"
        "CLÁUSULA DÉCIMA TERCEIRA - DO RECEBIMENTO\n"
        "13.1 A obra será recebida provisoriamente pela fiscalização, mediante termo circunstanciado, "
        "em até 15 dias da comunicação de conclusão, e definitivamente por comissão designada, em até "
        "90 dias do recebimento provisório, após a verificação da adequação do objeto.\n\n"
        "CLÁUSULA DÉCIMA QUARTA - DA PUBLICAÇÃO E DO FORO\n"
        "14.1 O extrato deste contrato será publicado no Diário Oficial do Município.\n"
        "14.2 Fica eleito o foro da comarca para dirimir as questões decorrentes deste contrato.\n\n"
        "E, por estarem de acordo, as partes assinam este instrumento em duas vias, na presença das "
        "testemunhas abaixo.\n\n"
        + _local_data("2026-04-06") + "\n\n"
        f"{PREFEITO[0]} - Prefeito Municipal - CONTRATANTE\n"
        f"Beatriz Costa - Sócia-administradora - CONTRATADA\n\n"
        "Testemunhas: Fernanda Rocha - Tiago Moreira",
    ))


# --- Volume 2: da assinatura do contrato ao arquivamento ------------------

def _memorando_medicao(arquivo: str) -> Peca:
    return Peca(arquivo, "MEMORANDO", "2026-05-20", FISCAL[0], (
        "MEMORANDO Nº 19/2026 - Fiscalização\n\n" + _local_data("2026-05-20") + "\n\n"
        "De: Fiscalização do Contrato nº 9/2026\nPara: Secretaria Municipal de Obras\n\n"
        f"Assunto: Boletim de medição nº 1 - reforma da {ESCOLA}.\n\n"
        "Senhora Secretária,\n\n"
        "Encaminho o boletim de medição nº 1, referente ao período de 13 de abril a 15 de maio de "
        "2026, conferido no local em 18 de maio, para ateste e pagamento.\n\n"
        "Serviços medidos: canteiro e tapumes (100%), demolição da cobertura do bloco B (100%), "
        "estrutura metálica do bloco B (80%), telhas do bloco B (40%), remoção do reservatório antigo "
        "(100%). Valor medido: R$ 138.400,00, correspondente a 29,9% do valor contratual, dentro do "
        "limite de 30% da cláusula sexta.\n\n"
        "O cronograma está sendo cumprido; registro apenas um atraso de três dias na entrega das "
        "telhas, recuperado na semana seguinte. Não há pendências de segurança do trabalho.\n\n"
        + _assina(FISCAL, "Atenciosamente,"),
    ))


def _volume_2() -> list[Peca]:
    pecas: list[Peca] = []

    pecas.append(Peca(V2, "TERMO", "2026-04-01", PROTOCOLO[0], (
        "TERMO DE ABERTURA DE VOLUME\n\n"
        f"Ao primeiro dia do mês de abril de 2026, abro o volume 2 do processo nº {PROCESSO}, em "
        "continuação ao volume 1, encerrado na folha 35. Este volume se inicia na folha 36.\n\n"
        "Para constar, lavrei o presente termo.\n\n"
        + _local_data("2026-04-01") + _assina(PROTOCOLO),
    )))

    pecas.append(_contrato(V2))

    pecas.append(Peca(V2, "PORTARIA", "2026-04-08", PREFEITO[0], (
        "PORTARIA Nº 61/2026\n\n"
        "Designa fiscal do Contrato nº 9/2026.\n\n"
        f"O PREFEITO MUNICIPAL DE {MUNICIPIO.upper()}, no uso de suas atribuições legais,\n\n"
        "RESOLVE:\n\n"
        "Art. 1º Designar o servidor Paulo Ramos, engenheiro civil da Secretaria Municipal de Obras, "
        f"como fiscal do Contrato nº 9/2026, celebrado com {CONSTRUTORA} para a reforma geral da "
        f"{ESCOLA}, e a servidora Helena Prado, diretora da escola, como fiscal auxiliar para os "
        "assuntos de funcionamento da unidade durante a obra.\n\n"
        "Art. 2º Compete ao fiscal manter o diário de obra, atestar as medições, comunicar à "
        "Secretaria de Obras as ocorrências que exijam providência e suspender serviços executados em "
        "desacordo com o projeto.\n\n"
        "Art. 3º Esta portaria entra em vigor na data de sua publicação.\n\n"
        + _local_data("2026-04-08") + _assina(PREFEITO),
    )))

    pecas.append(Peca(V2, "OFÍCIO", "2026-04-10", SEC_OBRAS[0], (
        "OFÍCIO Nº 41/2026 - SMO\n\n" + _local_data("2026-04-10") + "\n\n"
        f"À Senhora\nBeatriz Costa\nSócia-administradora\n{CONSTRUTORA}\n\n"
        "Assunto: Ordem de início dos serviços - Contrato nº 9/2026.\n\n"
        "Senhora Representante,\n\n"
        f"Comunico que os serviços de reforma geral da {ESCOLA} devem ter início em 13 de abril de "
        "2026, data a partir da qual se conta o prazo de execução de 150 dias previsto na cláusula "
        "quarta do contrato, com término em 9 de setembro de 2026.\n\n"
        "A primeira etapa compreende o bloco B, cujas salas serão desocupadas pela escola até 12 de "
        "abril. O fiscal do contrato, engenheiro Paulo Ramos, fará a reunião de abertura do canteiro "
        "no dia 13, às 8h, no local.\n\n"
        "Solicito a apresentação, até o início dos serviços, da anotação de responsabilidade técnica "
        "da obra e do programa de condições e meio ambiente de trabalho.\n\n"
        + _assina(SEC_OBRAS, "Atenciosamente,"),
    )))

    pecas.append(Peca(V2, "", "2026-05-05", FISCAL[0], (
        "Registro de acompanhamento da obra - 1ª visita documentada\n\n"
        f"Contrato nº 9/2026 - {ESCOLA}\nData: 05/05/2026\n\n"
        "Descrição das imagens juntadas em seguida:\n\n"
        "Foto 1 - Vista geral do bloco B a partir do pátio, com a cobertura antiga removida e a "
        "estrutura metálica nova montada em 60% da extensão. Tapume de compensado separando a área de "
        "obra do pátio.\n\n"
        "Foto 2 - Detalhe do apoio da estrutura metálica sobre a cinta de amarração, com chumbadores "
        "químicos conforme o projeto executivo aprovado em 20 de abril.\n\n"
        "Foto 3 - Reservatório de fibrocimento removido e base do novo reservatório em concretagem, "
        "com formas e armadura conferidas antes do lançamento.\n\n"
        "Foto 4 - Caçamba de entulho licenciada posicionada junto ao portão de serviço, sem acúmulo de "
        "material fora dela.",
        "Foto 5 - Sala 7 do bloco B com o forro retirado e a fiação antiga exposta, já desligada do "
        "quadro geral, aguardando a passagem dos novos eletrodutos.\n\n"
        "Foto 6 - Operários com capacete, botas e cinto de segurança trabalhando na estrutura, com "
        "linha de vida instalada.\n\n"
        "Observações do fiscal:\n"
        "- O andamento é compatível com o cronograma; a montagem da estrutura metálica está adiantada "
        "em relação ao previsto e a entrega das telhas, três dias atrasada.\n"
        "- A diretora relatou ruído excessivo no horário de provas do dia 29 de abril; a contratada "
        "concordou em concentrar os serviços de corte entre 12h e 13h30 e após as 17h.\n"
        "- Não há ocorrências de segurança.\n\n"
        "Paulo Ramos - fiscal do contrato",
    )))

    pecas.append(_memorando_medicao(V2))

    pecas.append(Peca(V2, "NOTA FISCAL", "2026-05-22", "Construtora Horizonte Azul", (
        "NOTA FISCAL DE SERVIÇOS ELETRÔNICA - NFS-e\n\n"
        "Número: 1041          Data de emissão: 22/05/2026          Código de verificação: FICT-1041\n\n"
        f"PRESTADOR\n{CONSTRUTORA}\nCNPJ: {CNPJ_CONSTRUTORA}\nInscrição municipal: 00000-0\n"
        "Avenida dos Ipês, 850 - Distrito Industrial - " + MUNICIPIO + "\n\n"
        f"TOMADOR\n{PREFEITURA}\nCNPJ: 22.222.222/0001-22\nRua das Palmeiras, 100 - Centro - {MUNICIPIO}\n\n"
        "DISCRIMINAÇÃO DOS SERVIÇOS\n"
        f"Reforma geral da {ESCOLA} - Contrato nº 9/2026 - Boletim de medição nº 1 - período de "
        "13/04/2026 a 15/05/2026: canteiro e tapumes, demolição da cobertura do bloco B, estrutura "
        "metálica do bloco B (80%), telhas do bloco B (40%), remoção do reservatório antigo.\n\n"
        "Valor dos serviços: R$ 138.400,00\n"
        "Retenções: ISS 3% (R$ 4.152,00); INSS 11% sobre a mão de obra (R$ 7.612,00)\n"
        "Valor líquido: R$ 126.636,00\n\n"
        "Dados bancários para pagamento: Banco 000, agência 0000, conta 00000-0.\n"
        "Documento fictício, emitido para fins de demonstração.",
    )))

    pecas.append(Peca(V2, "DESPACHO", "2026-05-26", SEC_OBRAS[0], (
        "DESPACHO\n\n"
        f"Processo nº {PROCESSO} - Contrato nº 9/2026\n\n"
        "1. Atesto a execução dos serviços constantes do boletim de medição nº 1, conferido pela "
        "fiscalização em 18 de maio de 2026, no valor de R$ 138.400,00, conforme o Memorando nº "
        "19/2026.\n\n"
        "2. Autorizo o pagamento da Nota Fiscal nº 1041, de 22 de maio de 2026, observadas as "
        "retenções legais, após a conferência das certidões de regularidade pela Controladoria.\n\n"
        "3. À Secretaria de Finanças para empenho e pagamento.\n\n"
        + _local_data("2026-05-26") + _assina(SEC_OBRAS),
    )))

    pecas.append(Peca(V2, "OFÍCIO", "2026-06-15", SOCIA[0], (
        f"OFÍCIO Nº 7/2026 - {CONSTRUTORA}\n\n" + _local_data("2026-06-15") + "\n\n"
        f"À Senhora\n{SEC_OBRAS[0]}\n{SEC_OBRAS[1]}\n\n"
        "Assunto: Pedido de prorrogação do prazo de execução - Contrato nº 9/2026.\n\n"
        "Senhora Secretária,\n\n"
        "1. Em complemento à mensagem eletrônica enviada em 12 de junho, formalizo o pedido de "
        "prorrogação do prazo de execução do Contrato nº 9/2026 por 45 dias.\n\n"
        "2. Entre 25 de maio e 11 de junho de 2026 choveu em 14 dos 18 dias, com acumulado de 312 mm "
        "segundo a estação meteorológica municipal, o que impediu a montagem das telhas do bloco A e a "
        "concretagem da rampa de acessibilidade, serviços que não podem ser executados sob chuva. O "
        "diário de obra registra as paralisações dia a dia.",
        "3. A paralisação atingiu o caminho crítico do cronograma: a cobertura do bloco A condiciona a "
        "desocupação do bloco C, última etapa, e o início de suas obras.\n\n"
        "4. Comprometemo-nos a manter duas equipes em turnos estendidos, sem custo adicional para o "
        "Município, de modo a reduzir o atraso efetivo. Ainda assim, a conclusão segura dos serviços "
        "exige a prorrogação solicitada, sem alteração de valor.\n\n"
        "5. Segue anexo o relatório pluviométrico e a cópia das páginas do diário de obra do período.\n\n"
        + _assina(SOCIA, "Atenciosamente,"),
    )))

    pecas.append(Peca(V2, "PARECER", "2026-06-22", FISCAL[0], (
        "PARECER TÉCNICO Nº 3/2026 - Fiscalização\n\n"
        f"Contrato nº 9/2026 - Processo nº {PROCESSO}\n"
        f"Assunto: Pedido de prorrogação de prazo formulado pela {CONSTRUTORA}.\n\n"
        "1. A contratada pede 45 dias de prorrogação em razão das chuvas de 25 de maio a 11 de junho "
        "de 2026.\n\n"
        "2. O diário de obra, que acompanho e assino, confirma a paralisação total dos serviços de "
        "cobertura e de concretagem em 12 dias do período e parcial em outros 2. Os dados da estação "
        "municipal confirmam o acumulado de 312 mm, cerca de 2,5 vezes a média histórica do período.\n\n"
        "3. Nos dias de chuva a contratada remanejou as equipes para os serviços internos do bloco B "
        "(instalações elétricas e pintura), que avançaram além do previsto. O atraso efetivo no "
        "caminho crítico, portanto, é menor que o número de dias paralisados.",
        "4. Pelo cronograma revisto que elaborei com a contratada, o atraso recuperável com os turnos "
        "estendidos oferecidos deixa um saldo de 28 dias no caminho crítico. Considero suficiente a "
        "prorrogação de 30 dias, e não os 45 pedidos.\n\n"
        "5. O fato é superveniente, alheio à vontade da contratada e devidamente documentado, "
        "enquadrando-se na hipótese de prorrogação da cláusula quarta do contrato, sem acréscimo de "
        "valor.\n\n"
        "6. Opino pelo deferimento parcial do pedido, com prorrogação de 30 dias do prazo de execução e "
        "da vigência, mediante termo aditivo, com novo término em 9 de outubro de 2026.\n\n"
        + _local_data("2026-06-22") + "\n\n" + FISCAL[0] + "\n" + FISCAL[1],
    )))

    pecas.append(Peca(V2, "DECISÃO", "2026-06-26", SEC_OBRAS[0], (
        "DECISÃO\n\n"
        f"Processo nº {PROCESSO} - Contrato nº 9/2026\n"
        f"Assunto: Pedido de prorrogação de prazo - {CONSTRUTORA}\n\n"
        "1. Acolho o Parecer Técnico nº 3/2026 da fiscalização, pelos seus fundamentos, e DEFIRO EM "
        "PARTE o pedido formulado no Ofício nº 7/2026 da contratada, prorrogando o prazo de execução "
        "do Contrato nº 9/2026 por 30 (trinta) dias, com novo término em 9 de outubro de 2026, e a "
        "vigência por igual período, sem alteração de valor.\n\n"
        "2. A contratada fica obrigada aos turnos estendidos oferecidos, sem custo para o Município, "
        "e a apresentar cronograma físico-financeiro revisto em 5 dias.\n\n"
        "3. À Procuradoria-Geral para a elaboração do termo aditivo. Intime-se a contratada.\n\n"
        + _local_data("2026-06-26") + _assina(SEC_OBRAS),
    )))

    pecas.append(Peca(V2, "TERMO", "2026-07-01", PREFEITO[0], (
        "TERMO ADITIVO Nº 1 AO CONTRATO Nº 9/2026\n\n"
        f"Primeiro termo aditivo ao Contrato nº 9/2026, celebrado entre a {PREFEITURA} e a {CONSTRUTORA} "
        f"para a reforma geral da {ESCOLA}.\n\n"
        f"CONTRATANTE: {PREFEITURA}, representada pelo Prefeito Municipal, {PREFEITO[0]}.\n"
        f"CONTRATADA: {CONSTRUTORA}, CNPJ {CNPJ_CONSTRUTORA}, representada por Beatriz Costa.\n\n"
        "CLÁUSULA PRIMEIRA - DO OBJETO\n"
        "1.1 Este termo aditivo prorroga o prazo de execução do Contrato nº 9/2026 por 30 (trinta) "
        "dias, com novo término em 9 de outubro de 2026, e a vigência por igual período, com novo "
        "término em 1º de dezembro de 2026, em razão das chuvas excepcionais do período de 25 de maio "
        "a 11 de junho de 2026, conforme a Decisão de 26 de junho de 2026 e o Parecer Técnico nº 3/2026.",
        "CLÁUSULA SEGUNDA - DO VALOR\n"
        "2.1 A prorrogação não altera o valor do contrato, permanecendo em R$ 462.900,00.\n\n"
        "CLÁUSULA TERCEIRA - DAS OBRIGAÇÕES ADICIONAIS\n"
        "3.1 A contratada manterá duas equipes em turnos estendidos até a recuperação do cronograma, "
        "sem custo adicional, conforme o cronograma revisto apresentado em 30 de junho de 2026, que "
        "passa a integrar o contrato.\n\n"
        "CLÁUSULA QUARTA - DA RATIFICAÇÃO\n"
        "4.1 Ficam ratificadas as demais cláusulas do contrato original.\n\n"
        "CLÁUSULA QUINTA - DA PUBLICAÇÃO\n"
        "5.1 O extrato deste termo será publicado no Diário Oficial do Município.\n\n"
        + _local_data("2026-07-01") + "\n\n"
        f"{PREFEITO[0]} - Prefeito Municipal - CONTRATANTE\n"
        "Beatriz Costa - Sócia-administradora - CONTRATADA\n\n"
        "Testemunhas: Fernanda Rocha - Tiago Moreira",
    )))

    pecas.append(Peca(V2, "NOTA FISCAL", "2026-07-20", "Construtora Horizonte Azul", (
        "NOTA FISCAL DE SERVIÇOS ELETRÔNICA - NFS-e\n\n"
        "Número: 1077          Data de emissão: 20/07/2026          Código de verificação: FICT-1077\n\n"
        f"PRESTADOR\n{CONSTRUTORA}\nCNPJ: {CNPJ_CONSTRUTORA}\nInscrição municipal: 00000-0\n"
        "Avenida dos Ipês, 850 - Distrito Industrial - " + MUNICIPIO + "\n\n"
        f"TOMADOR\n{PREFEITURA}\nCNPJ: 22.222.222/0001-22\nRua das Palmeiras, 100 - Centro - {MUNICIPIO}\n\n"
        "DISCRIMINAÇÃO DOS SERVIÇOS\n"
        f"Reforma geral da {ESCOLA} - Contrato nº 9/2026 - Boletins de medição nº 2 e nº 3 - período "
        "de 16/05/2026 a 15/07/2026: conclusão da cobertura do bloco B, instalações elétricas e pintura "
        "do bloco B, cobertura do bloco A (70%), reservatório novo instalado, banheiros dos blocos A e B.\n\n"
        "Valor dos serviços: R$ 201.750,00\n"
        "Retenções: ISS 3% (R$ 6.052,50); INSS 11% sobre a mão de obra (R$ 11.096,25)\n"
        "Valor líquido: R$ 184.601,25\n\n"
        "Dados bancários para pagamento: Banco 000, agência 0000, conta 00000-0.\n"
        "Documento fictício, emitido para fins de demonstração.",
    )))

    pecas.append(Peca(V2, "ATA", "2026-08-14", FISCAL[0], (
        "ATA DE VISTORIA E RECEBIMENTO PROVISÓRIO\n\n"
        f"Contrato nº 9/2026 - Processo nº {PROCESSO}\n\n"
        f"Aos quatorze dias do mês de agosto de 2026, às 9h, na {ESCOLA}, reuniram-se o fiscal do "
        "contrato, engenheiro Paulo Ramos, a fiscal auxiliar e diretora da escola, Helena Prado, e a "
        f"representante da contratada, Beatriz Costa, para a vistoria dos serviços executados no bloco "
        "B e no bloco A, cuja conclusão foi comunicada pela contratada em 10 de agosto de 2026.\n\n"
        "1. Bloco B\n"
        "Cobertura nova completa, sem infiltração verificada após o teste de aspersão; instalações "
        "elétricas com quadro de distribuição próprio, circuitos identificados e luminárias LED; "
        "banheiros reformados, com sanitário acessível em funcionamento; pintura concluída. Pendência: "
        "ajuste da porta do sanitário acessível, que não fecha por completo.",
        "2. Bloco A\n"
        "Cobertura nova completa; quadro geral novo com DR, testado; reservatório de 15 mil litros "
        "instalado e em operação; banheiros reformados; pintura externa concluída e interna em 90%. "
        "Pendências: pintura interna das salas 1 e 2 e instalação do piso tátil do corredor.\n\n"
        "3. Bloco C\n"
        "Serviços em andamento, fora do escopo desta vistoria, com término previsto para 9 de outubro "
        "de 2026.\n\n"
        "4. Conclusão\n"
        "Os serviços dos blocos A e B são RECEBIDOS PROVISORIAMENTE, com as pendências acima a serem "
        "sanadas em 15 dias, sem prejuízo do recebimento definitivo da obra completa, após a conclusão "
        "do bloco C.\n\n"
        "Nada mais havendo, lavrou-se a presente ata, assinada pelos presentes.\n\n"
        "Paulo Ramos - fiscal do contrato\nHelena Prado - fiscal auxiliar\nBeatriz Costa - contratada",
    )))

    pecas.append(Peca(V2, "CERTIDÃO", "2026-08-18", CONTROLADOR[0], (
        "CERTIDÃO\n\n"
        f"Certifico, para instrução do processo nº {PROCESSO}, que os pagamentos efetuados à "
        f"{CONSTRUTORA} à conta do Contrato nº 9/2026 até esta data, no total de R$ 340.150,00 "
        "(Notas Fiscais nº 1041 e nº 1077), foram precedidos de medição atestada pela fiscalização, de "
        "verificação das certidões de regularidade fiscal e trabalhista e de retenção dos tributos "
        "devidos, e que não há pendência registrada nesta Controladoria quanto à execução financeira "
        "do contrato.\n\n"
        "Certifico ainda que o Termo Aditivo nº 1 foi publicado em 3 de julho de 2026, na edição nº "
        "1.291 do Diário Oficial do Município.\n\n"
        + _local_data("2026-08-18") + _assina(CONTROLADOR),
    )))

    pecas.append(Peca(V2, "RESOLUÇÃO", "2026-08-20", "Conselho Municipal de Educação (CME)", (
        "RESOLUÇÃO Nº 2/2026 - CME\n\n"
        f"Dispõe sobre o calendário escolar da {ESCOLA} durante a etapa final da reforma do prédio.\n\n"
        f"O CONSELHO MUNICIPAL DE EDUCAÇÃO DE {MUNICIPIO.upper()}, no uso de suas atribuições, "
        "considerando a Ata de Vistoria e Recebimento Provisório de 14 de agosto de 2026 e a "
        "solicitação da direção da escola,\n\n"
        "RESOLVE:\n\n"
        "Art. 1º Autorizar, de 24 de agosto a 9 de outubro de 2026, o funcionamento das turmas do bloco "
        "C nos blocos A e B em regime de turno estendido, com reposição das aulas que não puderem ser "
        "ministradas, de modo a cumprir os 200 dias letivos.\n\n"
        "Art. 2º A direção da escola apresentará a este Conselho, até 30 de outubro de 2026, o relatório "
        "de cumprimento do calendário.\n\n"
        "Art. 3º Esta resolução entra em vigor na data de sua publicação.\n\n"
        + _local_data("2026-08-20") + "\n\nConselho Municipal de Educação (CME)\nSônia Ribeiro - Presidente",
    )))

    pecas.append(Peca(V2, "", "2026-08-25", "", (
        f"Lista de verificação - pendências do recebimento provisório (blocos A e B)\n\n"
        f"Contrato nº 9/2026 - {ESCOLA}\nVerificação realizada em 25/08/2026\n\n"
        "[x] Porta do sanitário acessível do bloco B ajustada - fecha e trava.\n"
        "[x] Pintura interna das salas 1 e 2 do bloco A concluída, duas demãos.\n"
        "[x] Piso tátil direcional e de alerta instalado no corredor do bloco A.\n"
        "[x] Teste de aspersão repetido na cobertura do bloco A após a última chuva - sem infiltração.\n"
        "[x] Quadro geral: etiquetas de identificação dos circuitos conferidas.\n"
        "[ ] Entrega do manual de uso e manutenção da cobertura - prometido para 05/09.\n"
        "[ ] Entrega do as built das instalações elétricas - prometido para 05/09.\n\n"
        "Observação: as duas pendências restantes são documentais e não impedem o uso dos blocos.",
    )))

    pecas.append(Peca(V2, "DESPACHO", "2026-08-28", SEC_EDUCACAO[0], (
        "DESPACHO\n\n"
        f"Processo nº {PROCESSO}\n\n"
        "1. Ciente da Ata de Vistoria e Recebimento Provisório de 14 de agosto de 2026, da Certidão da "
        "Controladoria de 18 de agosto e da Resolução nº 2/2026 do Conselho Municipal de Educação.\n\n"
        "2. Os blocos A e B retornam ao uso pleno da escola em 31 de agosto de 2026, com as turmas do "
        "bloco C acomodadas conforme a resolução do Conselho até a conclusão da obra.\n\n"
        "3. Encerre-se este volume. A instrução prossegue no volume 3 com o acompanhamento da etapa "
        "final e o recebimento definitivo.\n\n"
        + _local_data("2026-08-28") + _assina(SEC_EDUCACAO),
    )))

    pecas.append(Peca(V2, "TERMO", "2026-08-31", PROTOCOLO[0], (
        "TERMO DE ENCERRAMENTO DE VOLUME\n\n"
        f"Aos trinta e um dias do mês de agosto de 2026, encerro o volume 2 do processo nº {PROCESSO}, "
        "contendo 28 folhas numeradas e rubricadas, da folha 36 à folha 63, e abro o volume 3, que se "
        "inicia na folha 64.\n\n"
        "Para constar, lavrei o presente termo.\n\n"
        + _local_data("2026-08-31") + _assina(PROTOCOLO),
    )))
    return pecas


# --- Avulsos: outros formatos ------------------------------------------------

OFICIO_DIGITALIZADO = Peca("Contratos/oficio_digitalizado.png", "OFÍCIO", "2026-07-08", SEC_EDUCACAO[0], (
    "OFÍCIO Nº 58/2026 - SME\n\n" + _local_data("2026-07-08") + "\n\n"
    f"À Senhora\nBeatriz Costa\nSócia-administradora\n{CONSTRUTORA}\n\n"
    "Assunto: Horários de funcionamento da escola durante a etapa do bloco A.\n\n"
    "Senhora Representante,\n\n"
    "1. Com o início dos serviços no bloco A, previsto para 13 de julho, as turmas da manhã passam "
    "a ocupar o bloco B e o refeitório do bloco C, no horário das 7h30 às 11h50, e as turmas da tarde, "
    "das 13h às 17h20.\n\n"
    "2. Peço que os serviços de corte e demolição sejam concentrados entre 12h e 13h e após as 17h30, "
    "como já ajustado com a fiscalização para o bloco B, e que o acesso de caminhões ao canteiro se dê "
    "apenas pelo portão de serviço da Rua dos Jacarandás.\n\n"
    "3. A direção da escola, na pessoa da professora Helena Prado, fica à disposição para combinar as "
    "exceções que a obra exigir.\n\n"
    "Atenciosamente," + _assina(SEC_EDUCACAO),
))

PLANILHA_MEDICAO = Peca("Contratos/medicao_obra.xlsx", "", "2026-05-18", FISCAL[0], (
    "Medição nº 1 - Reforma da EM Prof. Aurora Lima - Contrato 9/2026",
))

PEDIDO_EML = Peca("Contratos/pedido_prorrogacao.eml", "", "2026-06-12", SOCIA[0], (
    "Pedido de prorrogação de prazo - Contrato 9/2026",
))

MEMORANDO_DOCX = _memorando_medicao("Contratos/memorando_fiscalizacao.docx")
CONTRATO_AVULSO = _contrato(CONTRATO_PDF)

PECAS: list[Peca] = (
    _volume_1() + _volume_2()
    + [CONTRATO_AVULSO, MEMORANDO_DOCX, PLANILHA_MEDICAO, OFICIO_DIGITALIZADO, PEDIDO_EML]
)

# --- Escrita dos arquivos ------------------------------------------------

_CRIACAO = dt.datetime(2026, 1, 1, 12, 0, 0)
_PDF_DATE = "D:20260101120000"
_A4 = (595, 842)
_MARGEM = 56
_FONTE, _NEGRITO, _CORPO = "helv", "hebo", 10


def _linhas_do_pdf(pecas: list[Peca]) -> list[tuple[int, Peca, str]]:
    """(índice da página na peça, peça, texto) na ordem do arquivo."""
    return [(i, peca, texto) for peca in pecas for i, texto in enumerate(peca.paginas)]


def _escrever_pdf(destino: Path, pecas: list[Peca], primeira_folha: int) -> None:
    import fitz

    doc = fitz.open()
    folha = primeira_folha
    for indice, peca, texto in _linhas_do_pdf(pecas):
        page = doc.new_page(width=_A4[0], height=_A4[1])
        cabecalho = fitz.Rect(_MARGEM, 28, _A4[0] - _MARGEM, 46)
        page.insert_textbox(cabecalho, f"{PREFEITURA.upper()}", fontname=_FONTE, fontsize=7, color=(0.35, 0.35, 0.35))
        if primeira_folha:  # volume encadernado: numeração de folha contínua
            page.insert_textbox(cabecalho, f"Processo nº {PROCESSO} - fl. {folha}", fontname=_FONTE, fontsize=7,
                                color=(0.35, 0.35, 0.35), align=fitz.TEXT_ALIGN_RIGHT)
        corpo = fitz.Rect(_MARGEM, 64, _A4[0] - _MARGEM, _A4[1] - _MARGEM)
        if indice == 0:
            titulo, _, resto = texto.partition("\n")
            page.insert_textbox(corpo, titulo, fontname=_NEGRITO, fontsize=12)
            corpo = fitz.Rect(_MARGEM, 86, _A4[0] - _MARGEM, _A4[1] - _MARGEM)
            texto = resto.lstrip("\n")
        sobra = page.insert_textbox(corpo, texto, fontname=_FONTE, fontsize=_CORPO, lineheight=1.25)
        assert sobra >= 0, f"texto não cabe na página {folha} de {destino.name}"
        assert len(texto) <= 1800, f"página {folha} de {destino.name} passa de 1800 caracteres"
        folha += 1
    doc.set_metadata({
        "title": destino.stem, "author": PREFEITURA, "creator": "GClaude Indexer - acervo de demonstração",
        "producer": "", "creationDate": _PDF_DATE, "modDate": _PDF_DATE,
    })
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc.save(destino, garbage=3, deflate=True)
    doc.close()


def _escrever_png(destino: Path, peca: Peca) -> None:
    """Um PDF de uma página renderizado a 150 dpi em tons de cinza: página
    sem camada de texto, como sai de um scanner."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=_A4[0], height=_A4[1])
    titulo, _, resto = peca.paginas[0].partition("\n")
    page.insert_textbox(fitz.Rect(_MARGEM, 64, _A4[0] - _MARGEM, 90), titulo, fontname=_NEGRITO, fontsize=12)
    sobra = page.insert_textbox(fitz.Rect(_MARGEM, 90, _A4[0] - _MARGEM, _A4[1] - _MARGEM), resto.lstrip("\n"),
                                fontname=_FONTE, fontsize=11, lineheight=1.3)
    assert sobra >= 0
    pix = page.get_pixmap(dpi=150, colorspace=fitz.csGRAY)
    destino.parent.mkdir(parents=True, exist_ok=True)
    pix.save(destino)
    doc.close()


def _escrever_docx(destino: Path, peca: Peca) -> None:
    import docx

    documento = docx.Document()
    titulo, _, resto = peca.paginas[0].partition("\n")
    documento.add_heading(titulo, level=1)
    for paragrafo in resto.strip("\n").split("\n\n"):
        documento.add_paragraph(paragrafo)
    props = documento.core_properties
    props.author = peca.autor
    props.created = props.modified = _CRIACAO
    props.title = titulo
    destino.parent.mkdir(parents=True, exist_ok=True)
    documento.save(destino)


def _escrever_xlsx(destino: Path, peca: Peca) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Medição 1"
    linhas = [
        [peca.paginas[0]],
        ["Período", "13/04/2026 a 15/05/2026", "", "Conferido em", "18/05/2026"],
        ["Responsável: Paulo Ramos - fiscal do contrato"],
        [],
        ["Item", "Serviço", "Unidade", "Qtde contratada", "Qtde medida", "Preço unitário (R$)", "Valor medido (R$)"],
        [1, "Canteiro de obras e tapumes", "vb", 1, 1, 18500.00, 18500.00],
        [2, "Demolição da cobertura - bloco B", "m²", 720, 720, 22.50, 16200.00],
        [3, "Estrutura metálica da cobertura - bloco B", "m²", 720, 576, 98.00, 56448.00],
        [4, "Telhas termoacústicas - bloco B", "m²", 720, 288, 112.00, 32256.00],
        [5, "Remoção do reservatório antigo", "vb", 1, 1, 4800.00, 4800.00],
        [6, "Base do reservatório novo", "vb", 1, 0.5, 20392.00, 10196.00],
        [],
        ["", "", "", "", "", "Total medido", 138400.00],
        ["", "", "", "", "", "Valor do contrato", 462900.00],
        ["", "", "", "", "", "Percentual acumulado", "29,9%"],
    ]
    for linha in linhas:
        ws.append(linha)
    wb.properties.creator = peca.autor
    wb.properties.created = wb.properties.modified = _CRIACAO
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)


def _escrever_eml(destino: Path, peca: Peca) -> None:
    corpo = (
        f"From: Beatriz Costa <contato@horizonteazul.exemplo>\r\n"
        f"To: Secretaria de Obras <obras@vilanovadosul.exemplo>\r\n"
        f"Cc: Paulo Ramos <paulo.ramos@vilanovadosul.exemplo>\r\n"
        f"Subject: {peca.paginas[0]}\r\n"
        f"Date: Fri, 12 Jun 2026 16:05:00 -0300\r\n"
        f"Message-ID: <20260612160500.000001@horizonteazul.exemplo>\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Transfer-Encoding: 8bit\r\n"
        f"\r\n"
        f"{MUNICIPIO}, 12 de junho de 2026.\r\n\r\n"
        f"Prezada Secretária Lúcia Martins,\r\n\r\n"
        f"Escrevo para antecipar o pedido que formalizaremos por ofício nos próximos dias: a "
        f"prorrogação do prazo de execução do Contrato nº 9/2026, da reforma da {ESCOLA}, por 45 dias.\r\n\r\n"
        f"Desde 25 de maio choveu em 14 dos 18 dias, com 312 mm acumulados segundo a estação municipal. "
        f"Não conseguimos montar as telhas do bloco A nem concretar a rampa de acessibilidade, e esses "
        f"serviços estão no caminho crítico do cronograma. O diário de obra, assinado pelo fiscal, "
        f"registra as paralisações.\r\n\r\n"
        f"Nos dias de chuva remanejamos as equipes para a parte elétrica e a pintura do bloco B, que "
        f"estão adiantadas. Propomos manter duas equipes em turnos estendidos, sem custo para o "
        f"Município, para reduzir o atraso.\r\n\r\n"
        f"Agradeço a atenção e fico à disposição para uma reunião no canteiro.\r\n\r\n"
        f"Atenciosamente,\r\n\r\n"
        f"Beatriz Costa\r\nSócia-administradora\r\n{CONSTRUTORA}\r\n"
        f"CNPJ {CNPJ_CONSTRUTORA} (fictício)\r\n"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(corpo.encode("utf-8"))


def gabarito(pecas: list[Peca]) -> list[tuple[str, int, int, str, str, str]]:
    """Linhas do CSV: páginas 1-based dentro de cada arquivo, na ordem das peças."""
    linhas = []
    proxima: dict[str, int] = {}
    for peca in pecas:
        inicio = proxima.get(peca.arquivo, 1)
        fim = inicio + len(peca.paginas) - 1
        proxima[peca.arquivo] = fim + 1
        linhas.append((peca.arquivo, inicio, fim, peca.tipo, peca.data, peca.autor))
    return linhas


def main(destino: Path | None = None) -> None:
    destino = Path(destino) if destino is not None else Path(__file__).parent
    acervo = destino / "acervo"

    volume_1 = [p for p in PECAS if p.arquivo == V1]
    volume_2 = [p for p in PECAS if p.arquivo == V2]
    _escrever_pdf(acervo / V1, volume_1, primeira_folha=1)
    _escrever_pdf(acervo / V2, volume_2, primeira_folha=1 + sum(len(p.paginas) for p in volume_1))
    _escrever_pdf(acervo / CONTRATO_PDF, [CONTRATO_AVULSO], primeira_folha=0)
    _escrever_docx(acervo / MEMORANDO_DOCX.arquivo, MEMORANDO_DOCX)
    _escrever_xlsx(acervo / PLANILHA_MEDICAO.arquivo, PLANILHA_MEDICAO)
    _escrever_png(acervo / OFICIO_DIGITALIZADO.arquivo, OFICIO_DIGITALIZADO)
    _escrever_eml(acervo / PEDIDO_EML.arquivo, PEDIDO_EML)

    with (destino / "gabarito.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["arquivo", "pagina_inicial", "pagina_final", "tipo", "data", "autor"])
        writer.writerows(gabarito(PECAS))

    total_paginas = sum(len(p.paginas) for p in PECAS)
    print(f"Acervo gerado em {acervo}: {len(PECAS)} peças, {total_paginas} páginas, "
          f"{len({p.arquivo for p in PECAS})} arquivos; gabarito em {destino / 'gabarito.csv'}.")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
