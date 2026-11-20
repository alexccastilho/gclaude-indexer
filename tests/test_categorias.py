"""Completude da tabela de categorias (`file_types.CATEGORY_TRAITS`).

Toda categoria tem família no formulário (ou é exceção declarada), tem rota
na conversão, e os conjuntos derivados da tabela são os de antes dela: os
valores esperados estão escritos aqui por extenso para que uma mudança
acidental na tabela apareça.
"""

from __future__ import annotations

from gclaude_indexer import auto_settings, conversion, file_types, settings_proposal, update_plan
from gclaude_indexer.file_types import (
    CATEGORY_FAMILIES, CATEGORY_TRAITS, EXTENSION_CATEGORIES, HEAD_READ_CATEGORIES, LIGHT_TEXT_CATEGORIES,
    MESSAGE_PAGE_CATEGORIES, PAGED_CATEGORIES, READ_AS_PDF_CATEGORIES, category_of_extension, conversion_queue,
)

# Mostrada à parte no formulário (opt-in, caixa própria).
SEM_FAMILIA = {"midia"}


def test_tabela_e_extensoes_tem_as_mesmas_categorias():
    assert list(CATEGORY_TRAITS) == list(EXTENSION_CATEGORIES)


def test_toda_categoria_tem_familia_ou_e_excecao_declarada():
    sem_familia = {nome for nome, traits in CATEGORY_TRAITS.items() if traits.family is None}
    assert sem_familia == SEM_FAMILIA
    em_familias = [c for categorias in CATEGORY_FAMILIES.values() for c in categorias]
    assert sorted(em_familias) == sorted(set(EXTENSION_CATEGORIES) - SEM_FAMILIA)


def test_familias_na_ordem_do_formulario():
    assert list(CATEGORY_FAMILIES.items()) == [
        ("documentos", ("pdf", "docx", "xlsx", "pptx", "opendocument", "rtf", "paginados", "legados")),
        ("imagens", ("imagens",)),
        ("text_data", ("text", "legendas", "web_dados")),
        ("mensagens", ("email", "mbox", "outlook")),
        ("tecnicos", ("cad", "assinados")),
    ]


def test_toda_categoria_tem_rota_de_conversao():
    filas_proprias = {"outlook", "midia"}
    for categoria in EXTENSION_CATEGORIES:
        if categoria in filas_proprias:
            assert categoria not in conversion._CONVERTERS
        else:
            assert categoria in conversion._CONVERTERS, categoria
    assert set(conversion._LIGHT_TEXT_EXTRACTORS) == LIGHT_TEXT_CATEGORIES


def test_filas_da_conversao():
    assert {categoria: conversion_queue(categoria) for categoria in EXTENSION_CATEGORIES} == {
        "pdf": "heavy", "imagens": "heavy", "paginados": "heavy", "assinados": "heavy",
        "legados": "legacy", "outlook": "outlook", "midia": "media",
        "docx": "light", "xlsx": "light", "pptx": "light", "opendocument": "light", "rtf": "light",
        "text": "light", "legendas": "light", "web_dados": "light", "email": "light", "mbox": "light",
        "cad": "light",
    }
    # Extensão sem categoria: a regra "all", na fila leve.
    assert conversion_queue(None) == "light"


def test_conjuntos_derivados_sao_os_de_antes():
    paginadas = {"pdf", "imagens", "paginados", "legados"}
    assert set(PAGED_CATEGORIES) == paginadas
    assert set(MESSAGE_PAGE_CATEGORIES) == {"mbox", "outlook", "midia"}
    assert set(READ_AS_PDF_CATEGORIES) == {"pdf", "paginados", "legados"}
    assert LIGHT_TEXT_CATEGORIES == {
        "docx", "xlsx", "pptx", "text", "web_dados", "email", "opendocument", "rtf", "mbox", "cad", "legendas",
    }
    assert conversion._TEXT_CATEGORIES == LIGHT_TEXT_CATEGORIES
    assert HEAD_READ_CATEGORIES == {"text", "web_dados"}
    assert set(auto_settings._MULTI_PAGE_CATEGORIES) == paginadas
    assert settings_proposal._MULTI_PAGE_CATEGORIES == paginadas
    assert set(update_plan._MAYBE_SEVERAL_PAGES) == {
        "pdf", "paginados", "legados", "assinados", "mbox", "outlook", "midia",
    }


def test_extensoes_html_dentro_de_web_dados():
    assert file_types.HTML_EXTENSIONS == {".html", ".htm", ".xhtml", ".xht", ".shtml"}
    assert file_types.MHTML_EXTENSIONS == {".mht", ".mhtml"}
    assert EXTENSION_CATEGORIES["web_dados"] == file_types.HTML_EXTENSIONS | file_types.MHTML_EXTENSIONS | {
        ".xml", ".json",
    }


def test_categoria_pela_extensao_igual_a_varredura_da_tabela():
    vistas: set[str] = set()
    for categoria, extensoes in EXTENSION_CATEGORIES.items():
        assert not (extensoes & vistas), categoria  # nenhuma extensão em duas categorias
        vistas |= extensoes
        for extensao in extensoes:
            assert category_of_extension(extensao) == categoria
            assert category_of_extension(extensao.upper()) == categoria
    assert category_of_extension(".xlt") is None
    assert category_of_extension("") is None
