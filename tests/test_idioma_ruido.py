"""2.1.3: idiomas exóticos tirados do ruído do OCR.

Uma folha de ponto escaneada ("08:00 | 12:00 | 14:00") lida pelo OCR vira um
texto sem idioma. O `py3langid` dava a ela iorubá, lígure, occitano, lingala
com probabilidade de 0,02 (quase uniforme), e o arquivo, em português, era
lido com `script/Latin+oci+yor`: 89 MB baixados para um OCR pior. No acervo
convertido, todo trecho com probabilidade de 0,5 ou mais era português; os
códigos exóticos estavam todos abaixo de 0,3.
"""

from __future__ import annotations

from gclaude_indexer import language_detect

FOLHA_DE_PONTO = (
    "01 S AWE $ 3 7 ; SABADO\n02 A AA gi - - - : DOMINGO\n03 08:00 | 12:00 | 14:00 | 18:00\n"
    "04 | 08:00 | 12:00 | 14:00 | 18:00\n05 | 08:00 | 12:00 | 14:00 | 18:00\n"
    "06 | 08:00 | 12:00 | 14:00 | 18:00\n07 | 08:00 12:00 | 14:00 18:00 |\nTEREE\n \n"
    "EO TO IP II O AI EL HEAT SÁBADO\n09 OGE A Igu De DOMINGO\n10 08:00 | 12:00 | 14:00 |18:00\n"
    "11 | 08:00 | 12:00 | 14:00 | 18:00\n12 | 08:00 | 12:00 | 14:00 | 18:00\n"
    "13 | 08:00 | 12:00 | 14:00 | 18:00\n"
    "14 | 08:00 | 12:00 |_ 14:00 | 18:00\n45. Lo 4 EES - - ES SÁBADO\n"
    "46:1 285:2 - _ - - - - _ DOMINGO\n17 | 08:00 | 12:00 | 14:00 | 18:00 a\n \nA\n"
    "18 08:00 112:00. 14:00 ! 18:00 a 7 O\n19 | 08:00 | 12:00 | 14:00 | 18:00 A RET\n \nP\n"
    "20 | 08:00 | 12:00) 14:00 | 18:00 l\n \nR Fẹ\n21 | 08:00 | 12:00 | 14:00 | 18:00 < ZE\n \n"
    "nar\n \nd\n24 2 MURE NI E - D SABADO\n23 e PO II ELU A HILL HS DOMINGO\n"
    "24 | 08:00 | 14:00 | 14:00 |18:00 E"
)

PORTUGUES = (
    "O Conselho Regional de Odontologia de São Paulo, no uso das atribuições que lhe "
    "confere a lei, resolve aprovar o parecer da comissão de ética e determinar o "
    "arquivamento do processo administrativo instaurado contra o profissional, "
    "por não haver provas suficientes da infração apontada na denúncia recebida."
)


def test_ruido_de_ocr_nao_vira_idioma():
    assert language_detect.detect_languages(FOLHA_DE_PONTO) == []


def test_ruido_nao_entra_ao_lado_do_portugues():
    assert language_detect.detect_languages(PORTUGUES + "\n" + FOLHA_DE_PONTO) == ["pt"]


def test_texto_real_continua_detectado():
    assert language_detect.detect_languages(PORTUGUES) == ["pt"]


# Formulário gerado com espaço entre cada caractere (texto nativo do PDF):
# "d e s c r e v e r o m o t i v o". Letra solta não tem idioma; o
# `py3langid` dava lígure com 0,52 e o arquivo era lido com `script/Latin`.
LETRAS_ESPACADAS = (
    # Nomes, números e código inventados; o formato é o do formulário real.
    "M a r i a d a S i l v a P e r e i r a\nC o o r d o s t a d u\ng s t a d u a l\nd e S a u d e\n"
    "E m : D e c r t o n º 0 0 0 0\n1 2 3 4 5 6 7 8\nD i g i t a l i z a d o c o m C a m S c a n n e r\n"
    "Para verificar as assinaturas, acesse www.exemplo.gov.br/autenticidade e informe o código 12345678.\n"
    "S E S A\nS E C R E T A R I A\nD A\nS A Ú D E\n"
    "0 2\nE m :\nJ o ã o d e S o u z a L i m a\nC o o r d e n a d o r E s t a d u n l\n"
    "d e S a u d e B u c a l\nB e c 0 0 0 0 0 0 0 0 0 0 S E S A\nD I A\n"
    "d e s c r e v e r o m o t i v o e a s s i n a r\nM O T I V O\nA S S I N A T U R A\n"
    "C h e f i a I m e d i a t a ( A s s i n a t u r a e C a r i m b o )\n"
)


def test_letras_espacadas_nao_viram_idioma():
    assert language_detect.detect_languages(LETRAS_ESPACADAS) == []


def test_letras_espacadas_ao_lado_do_portugues():
    assert language_detect.detect_languages(PORTUGUES + "\n" + LETRAS_ESPACADAS) == ["pt"]
