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
