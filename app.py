# -*- coding: utf-8 -*-
"""
Inspector BIM — Edificação de Apoio Agrícola
Master em IA para Arquitectura, Engenharia e Construção — Zigurat Institute of Technology
Módulo 5 — Tema 2: Agentic IA | Tarefa Individual | Daniel Veludo
"""

# ============================================================
# Imports
# ============================================================

import os
import json
import re
import tempfile
from datetime import datetime
from typing import TypedDict, Annotated, List, Optional

import streamlit as st

# LangGraph
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

# LangChain
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# Saídas Word e Excel
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ============================================================
# Estado Partilhado
# ============================================================

class EstadoInspectorAgricola(TypedDict):
    """Estado partilhado entre todos os agentes do sistema."""
    messages:         Annotated[list, add_messages]
    caminho_ifc:      str
    elementos_ifc:    Optional[dict]
    verificacao:      Optional[dict]
    medicoes:         Optional[dict]
    recomendacoes_llm: Optional[str]
    saidas:           Optional[dict]


# ============================================================
# AGENTE 1 — Extrator IFC
# ============================================================

def agente_extrator_ifc(estado: EstadoInspectorAgricola) -> dict:
    """Lê o ficheiro IFC e extrai todos os elementos relevantes."""
    import ifcopenshell
    import ifcopenshell.util.element

    caminho = estado["caminho_ifc"]
    st.write(f"🔍 **[Agente Extrator IFC]** A abrir: `{caminho}`")

    modelo = ifcopenshell.open(caminho)

    # Projecto
    projecto_ifc = modelo.by_type("IfcProject")
    nome_projecto = projecto_ifc[0].LongName or projecto_ifc[0].Name if projecto_ifc else "Projecto IFC"
    nome_projecto = re.sub(r'\\X\\([0-9A-F]{2})', lambda m: chr(int(m.group(1), 16)), nome_projecto)

    # Pisos
    storeys_raw = modelo.by_type("IfcBuildingStorey")
    pisos = [
        {"nome": s.Name or "Sem nome", "elevacao": round(s.Elevation or 0.0, 3)}
        for s in storeys_raw
    ]

    # Paredes
    paredes_std  = modelo.by_type("IfcWallStandardCase")
    paredes_gen  = modelo.by_type("IfcWall")
    todas_paredes = list(paredes_std) + list(paredes_gen)
    tipos_parede = {}
    for p in todas_paredes:
        tipo = p.Name or "Desconhecido"
        tipo_limpo = re.sub(r':\d+$', '', tipo)
        tipos_parede[tipo_limpo] = tipos_parede.get(tipo_limpo, 0) + 1

    # Janelas
    janelas_raw = modelo.by_type("IfcWindow")
    janelas = []
    for j in janelas_raw:
        janelas.append({
            "nome": re.sub(r':\d+$', '', j.Name or "Janela"),
            "altura_m": round(j.OverallHeight or 0.0, 3),
            "largura_m": round(j.OverallWidth or 0.0, 3),
        })

    # Portas
    portas_raw = modelo.by_type("IfcDoor")
    portas = []
    for p in portas_raw:
        portas.append({
            "nome": re.sub(r':\d+$', '', p.Name or "Porta"),
            "altura_m": round(p.OverallHeight or 0.0, 3),
            "largura_m": round(p.OverallWidth or 0.0, 3),
        })

    # Lajes
    lajes_raw = modelo.by_type("IfcSlab")
    area_piso_m2 = 0.0
    lajes_piso = []
    for laje in lajes_raw:
        tipo_laje = getattr(laje, 'PredefinedType', None)
        if tipo_laje not in ('ROOF', 'BASESLAB'):
            lajes_piso.append(laje)
            try:
                psets = ifcopenshell.util.element.get_psets(laje)
                area = (
                    psets.get("Qto_SlabBaseQuantities", {}).get("NetArea")
                    or psets.get("Qto_SlabBaseQuantities", {}).get("GrossArea")
                    or psets.get("BaseQuantities", {}).get("NetArea")
                )
                if area:
                    area_piso_m2 += area
            except Exception:
                pass

    # Espaços
    espacos_raw = modelo.by_type("IfcSpace")
    espacos = []
    for e in espacos_raw:
        nome = e.LongName or e.Name or "Sem nome"
        nome = re.sub(r'\\X\\([0-9A-F]{2})', lambda m: chr(int(m.group(1), 16)), nome)
        numero = e.Name or "-"
        area = None
        try:
            psets = ifcopenshell.util.element.get_psets(e)
            area = (
                psets.get("Qto_SpaceBaseQuantities", {}).get("NetFloorArea")
                or psets.get("BaseQuantities", {}).get("NetFloorArea")
                or psets.get("Pset_SpaceCommon", {}).get("NetPlannedArea")
            )
        except Exception:
            area = None
        espacos.append({"numero": numero, "nome": nome, "area_m2": area})

    elementos = {
        "projecto":    nome_projecto,
        "pisos":       pisos,
        "paredes":     {"total": len(todas_paredes), "tipos": tipos_parede},
        "janelas":     janelas,
        "portas":      portas,
        "lajes":       {"total": len(lajes_raw)},
        "area_piso_m2": round(area_piso_m2, 2),
        "espacos":     espacos,
    }

    st.write(
        f"   ✅ Projecto: {nome_projecto} | "
        f"{len(todas_paredes)} paredes | {len(janelas)} janelas | "
        f"{len(portas)} portas | {len(lajes_raw)} lajes | {len(espacos)} espaços"
    )

    return {
        "elementos_ifc": elementos,
        "messages": [AIMessage(content=
            f"[Agente Extrator] Modelo: {nome_projecto} | "
            f"{len(todas_paredes)} paredes | {len(janelas)} janelas | "
            f"{len(portas)} portas | {len(lajes_raw)} lajes | {len(espacos)} espaços"
        )]
    }


# ============================================================
# AGENTE 2 — Verificador de Conformidade
# ============================================================

def agente_verificador(estado: EstadoInspectorAgricola) -> dict:
    """Verifica conformidade técnica dos elementos do modelo IFC."""
    st.write("📐 **[Agente Verificador]** A verificar critérios técnicos...")

    dados = estado["elementos_ifc"]
    aprovacoes = []
    nao_conformidades = []

    # CRITÉRIO 1: Largura mínima das portas (DL 163/2006)
    portas_estreitas = [p for p in dados["portas"] if p["largura_m"] < 0.80]
    if portas_estreitas:
        nao_conformidades.append(
            f"Acessibilidade (DL 163/2006) — {len(portas_estreitas)} porta(s) com largura < 0.80m: "
            + ", ".join(f"{p['nome']} ({p['largura_m']:.2f}m)" for p in portas_estreitas)
        )
    else:
        aprovacoes.append(
            f"Acessibilidade (DL 163/2006) — Todas as {len(dados['portas'])} portas têm largura ≥ 0.80m "
            f"(mín. encontrado: {min(p['largura_m'] for p in dados['portas']):.2f}m)"
        )

    # CRITÉRIO 2: Ventilação natural (Portaria 702/80)
    area_janelas = sum(j["largura_m"] * j["altura_m"] for j in dados["janelas"])
    area_piso = dados.get("area_piso_m2", 0)

    if area_janelas == 0:
        nao_conformidades.append(
            "Ventilação (Portaria 702/80) — Nenhuma janela encontrada no modelo"
        )
    elif area_piso > 0:
        racio = area_janelas / area_piso
        minimo = 0.10
        if racio >= minimo:
            aprovacoes.append(
                f"Ventilação (Portaria 702/80) — Rácio de {racio:.1%} "
                f"(janelas: {area_janelas:.2f} m² / piso: {area_piso:.2f} m²). "
                f"Cumpre o mínimo de {minimo:.0%}."
            )
        else:
            nao_conformidades.append(
                f"Ventilação (Portaria 702/80) — Rácio de {racio:.1%} "
                f"(janelas: {area_janelas:.2f} m² / piso: {area_piso:.2f} m²). "
                f"Não cumpre o mínimo de {minimo:.0%}."
            )
    else:
        aprovacoes.append(
            f"Ventilação (Portaria 702/80) — Área de janelas: {area_janelas:.2f} m² "
            f"({len(dados['janelas'])} janelas). "
            f"Área de pavimento não exportada — verificar rácio em obra."
        )

    # CRITÉRIO 3: Espaços funcionais obrigatórios
    nomes_espacos = [e["nome"].lower() for e in dados["espacos"]]
    espacos_necessarios = {
        "oficina ou ferramentaria": ["oficina", "ferramentaria"],
        "armazém de fitofármacos":  ["fitof", "armazém", "armaz"],
        "parque de máquinas":       ["parque", "máquinas", "maquinas"],
        "instalações sanitárias":   ["i.s.", "instalação", "sanitár", "wc"],
    }
    for descricao, palavras_chave in espacos_necessarios.items():
        encontrado = any(
            any(kw in nome for kw in palavras_chave)
            for nome in nomes_espacos
        )
        if encontrado:
            aprovacoes.append(f"Programa funcional — Espaço '{descricao}' identificado no modelo")
        else:
            nao_conformidades.append(f"Programa funcional — Espaço '{descricao}' não encontrado no modelo")

    # CRITÉRIO 4: Armazém de fitofármacos separado (DL 173/2005)
    fitof_espacos = [e for e in dados["espacos"] if "fitof" in e["nome"].lower()]
    if fitof_espacos:
        nome_fitof = fitof_espacos[0]["nome"]
        aprovacoes.append(
            f"DL 173/2005 — '{nome_fitof}' existe como espaço autónomo. "
            f"Verificar em obra: ventilação directa para o exterior e sinalética obrigatória."
        )

    # CRITÉRIO 5: IS separadas por género (DL 347/93 / Portaria 987/93)
    tem_is_fem  = any("feminina" in n or "duche f" in n or "cabine f" in n for n in nomes_espacos)
    tem_is_masc = any("masculina" in n or "duche m" in n or "cabine m" in n for n in nomes_espacos)
    if tem_is_fem and tem_is_masc:
        aprovacoes.append(
            "Higiene (DL 347/93 / Portaria 987/93) — IS Feminina e IS Masculina presentes e separadas"
        )
    elif tem_is_fem or tem_is_masc:
        nao_conformidades.append(
            "Higiene (DL 347/93 / Portaria 987/93) — Apenas um género de IS identificado; verificar separação"
        )
    else:
        nao_conformidades.append(
            "Higiene (DL 347/93 / Portaria 987/93) — IS não identificadas no modelo"
        )

    total  = len(aprovacoes) + len(nao_conformidades)
    pct    = round(len(aprovacoes) / total * 100) if total > 0 else 0
    resumo = f"{len(aprovacoes)} / {total} critérios aprovados ({pct}%)"

    st.write(f"   ✅ Aprovações: {len(aprovacoes)} | ❌ Não Conformidades: {len(nao_conformidades)} | {resumo}")

    return {
        "verificacao": {
            "aprovacoes": aprovacoes,
            "nao_conformidades": nao_conformidades,
            "resumo": resumo,
        },
        "messages": [AIMessage(content=
            f"[Agente Verificador] {len(aprovacoes)} aprovações | "
            f"{len(nao_conformidades)} não conformidades | "
            f"Conformidade: {resumo}"
        )]
    }


# ============================================================
# AGENTE 3 — Quantificador
# ============================================================

def agente_quantificador(estado: EstadoInspectorAgricola) -> dict:
    """Calcula métricas e medições dos elementos IFC."""
    st.write("📊 **[Agente Quantificador]** A calcular medições...")

    dados = estado["elementos_ifc"]
    area_janelas = sum(j["largura_m"] * j["altura_m"] for j in dados["janelas"])

    tipos_janela = {}
    for j in dados["janelas"]:
        tipos_janela[j["nome"]] = tipos_janela.get(j["nome"], 0) + 1

    tipos_porta = {}
    for p in dados["portas"]:
        tipos_porta[p["nome"]] = tipos_porta.get(p["nome"], 0) + 1

    espessuras = sorted(set(
        int(m) for tipo in dados["paredes"]["tipos"].keys()
        for m in re.findall(r'(\d+)\s*mm', tipo)
    ))

    medicoes = {
        "n_janelas":       len(dados["janelas"]),
        "area_janelas_m2": round(area_janelas, 2),
        "tipos_janela":    tipos_janela,
        "n_portas":        len(dados["portas"]),
        "tipos_porta":     tipos_porta,
        "n_paredes":       dados["paredes"]["total"],
        "tipos_parede":    dados["paredes"]["tipos"],
        "espessuras_mm":   espessuras,
        "n_lajes":         dados["lajes"]["total"],
        "n_espacos":       len(dados["espacos"]),
        "n_pisos":         len(dados["pisos"]),
    }

    st.write(
        f"   ✅ Janelas: {medicoes['n_janelas']} unid. | {medicoes['area_janelas_m2']} m² | "
        f"Portas: {medicoes['n_portas']} | Paredes: {medicoes['n_paredes']}"
    )

    return {
        "medicoes": medicoes,
        "messages": [AIMessage(content=
            f"[Agente Quantificador] {medicoes['n_janelas']} janelas "
            f"({medicoes['area_janelas_m2']} m²) | "
            f"{medicoes['n_portas']} portas | "
            f"{medicoes['n_paredes']} paredes"
        )]
    }


# ============================================================
# AGENTE 4 — Recomendações LLM (Condicional)
# ============================================================

def agente_recomendacoes(estado: EstadoInspectorAgricola) -> dict:
    """Usa o LLM para gerar recomendações técnicas sobre as não conformidades encontradas."""
    st.write("💡 **[Agente Recomendações LLM]** A gerar recomendações...")

    nao_conformidades = estado["verificacao"]["nao_conformidades"]
    dados = estado["elementos_ifc"]

    system_prompt = """És um engenheiro técnico especializado em edificações agrícolas e industriais em Portugal.
Para cada não conformidade identificada num modelo BIM (IFC), fornece:
1. Acção correctiva concreta e exequível
2. Referência normativa ou regulamentar aplicável (legislação portuguesa)
3. Prazo estimado de resolução
Sê técnico, directo e objectivo. Usa linguagem de relatório técnico em Português de Portugal."""

    nao_conformidades_texto = "\n".join(f"- {p}" for p in nao_conformidades)
    human_prompt = f"""Projecto: {dados['projecto']}
Tipo: Edificação de apoio agrícola (Casa de Máquinas)

Não Conformidades identificadas no modelo BIM:
{nao_conformidades_texto}

Para cada não conformidade, fornece a acção correctiva, referência normativa e prazo."""

    resposta = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ])

    st.write("   ✅ Recomendações geradas!")
    return {
        "recomendacoes_llm": resposta.content,
        "messages": [AIMessage(content=f"[Agente Recomendações] {resposta.content}")]
    }


# ============================================================
# Funções auxiliares de output (docx, xlsx, json)
# ============================================================

def gerar_docx(relatorio_txt, dados, verificacao):
    """Converte o relatório de texto para formato Word (.docx)."""
    doc = DocxDocument()

    titulo = doc.add_heading(dados["projecto"], level=0)
    titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph(f"Relatório de Inspecção BIM  |  {datetime.now().strftime('%d/%m/%Y')}")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    for linha in relatorio_txt.split("\n"):
        linha_strip = linha.strip()
        if not linha_strip:
            continue
        if linha_strip.startswith("## "):
            doc.add_heading(linha_strip[3:], level=1)
        elif linha_strip.startswith("### "):
            doc.add_heading(linha_strip[4:], level=2)
        elif linha_strip.startswith("- ") or linha_strip.startswith("* "):
            doc.add_paragraph(linha_strip[2:], style="List Bullet")
        elif linha_strip.startswith("**") and linha_strip.endswith("**"):
            p = doc.add_paragraph()
            p.add_run(linha_strip.strip("*")).bold = True
        else:
            doc.add_paragraph(linha_strip)

    doc.save("relatorio_inspector.docx")


def gerar_xlsx(verificacao, medicoes, dados):
    """Gera a checklist de conformidade em formato Excel (.xlsx)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Conformidade"
    ws.sheet_view.showGridLines = False

    cor_titulo = PatternFill("solid", fgColor="1B5E20")
    cor_ok = PatternFill("solid", fgColor="E8F5E9")
    cor_nok = PatternFill("solid", fgColor="FFEBEE")
    cor_hdr = PatternFill("solid", fgColor="2E7D32")
    fonte_titulo = Font(bold=True, color="FFFFFF", name="Calibri", size=12)
    fonte_hdr = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
    al_centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    al_esq = Alignment(horizontal="left", vertical="center", wrap_text=True)
    borda = Border(
        left=Side(style="thin", color="BDBDBD"),
        right=Side(style="thin", color="BDBDBD"),
        top=Side(style="thin", color="BDBDBD"),
        bottom=Side(style="thin", color="BDBDBD")
    )

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 65

    ws.merge_cells("A1:B1")
    c = ws["A1"]
    c.value = f"CHECKLIST DE CONFORMIDADE — {dados['projecto'].upper()}"
    c.fill = cor_titulo
    c.font = fonte_titulo
    c.alignment = al_centro
    ws.row_dimensions[1].height = 30

    ws.merge_cells("A2:B2")
    c = ws["A2"]
    c.value = f"Inspector BIM  |  {datetime.now().strftime('%d/%m/%Y')}"
    c.fill = PatternFill("solid", fgColor="388E3C")
    c.font = Font(color="FFFFFF", name="Calibri", size=10, italic=True)
    c.alignment = al_centro
    ws.row_dimensions[2].height = 18

    for col, hdr in zip(["A", "B"], ["Estado", "Critério / Descrição"]):
        c = ws[f"{col}3"]
        c.value = hdr
        c.fill = cor_hdr
        c.font = fonte_hdr
        c.alignment = al_centro
        c.border = borda
    ws.row_dimensions[3].height = 22

    linha = 4
    for a in verificacao["aprovacoes"]:
        ws.cell(linha, 1, "OK").fill = cor_ok
        ws.cell(linha, 1).font = Font(name="Calibri", size=10, color="1B5E20", bold=True)
        ws.cell(linha, 1).alignment = al_centro
        ws.cell(linha, 1).border = borda
        ws.cell(linha, 2, a).fill = cor_ok
        ws.cell(linha, 2).font = Font(name="Calibri", size=10, color="1B5E20")
        ws.cell(linha, 2).alignment = al_esq
        ws.cell(linha, 2).border = borda
        ws.row_dimensions[linha].height = 28
        linha += 1

    for n in verificacao["nao_conformidades"]:
        ws.cell(linha, 1, "NOK").fill = cor_nok
        ws.cell(linha, 1).font = Font(name="Calibri", size=10, color="B71C1C", bold=True)
        ws.cell(linha, 1).alignment = al_centro
        ws.cell(linha, 1).border = borda
        ws.cell(linha, 2, n).fill = cor_nok
        ws.cell(linha, 2).font = Font(name="Calibri", size=10, color="B71C1C")
        ws.cell(linha, 2).alignment = al_esq
        ws.cell(linha, 2).border = borda
        ws.row_dimensions[linha].height = 32
        linha += 1

    ws.merge_cells(f"A{linha}:B{linha}")
    c = ws.cell(linha, 1, f"RESULTADO: {verificacao['resumo']}")
    c.fill = cor_titulo
    c.font = fonte_titulo
    c.alignment = al_centro
    ws.row_dimensions[linha].height = 26

    ws2 = wb.create_sheet("Medicoes")
    ws2.sheet_view.showGridLines = False
    ws2.column_dimensions["A"].width = 35
    ws2.column_dimensions["B"].width = 25

    ws2.merge_cells("A1:B1")
    c = ws2["A1"]
    c.value = "MEDICOES"
    c.fill = cor_titulo
    c.font = fonte_titulo
    c.alignment = al_centro
    ws2.row_dimensions[1].height = 26

    for col, hdr in zip(["A", "B"], ["Elemento", "Quantidade"]):
        c = ws2[f"{col}2"]
        c.value = hdr
        c.fill = cor_hdr
        c.font = fonte_hdr
        c.alignment = al_centro
        c.border = borda
    ws2.row_dimensions[2].height = 22

    rows = [
        ("Janelas (unidades)", medicoes["n_janelas"]),
        ("Janelas (area m2)", medicoes["area_janelas_m2"]),
        ("Portas (unidades)", medicoes["n_portas"]),
        ("Paredes (total)", medicoes["n_paredes"]),
        ("Espessuras de parede (mm)", str(medicoes["espessuras_mm"])),
        ("Lajes", medicoes["n_lajes"]),
        ("Espacos funcionais", medicoes["n_espacos"]),
        ("Pisos", medicoes["n_pisos"]),
    ]
    for i, (elem, val) in enumerate(rows, 3):
        fill = PatternFill("solid", fgColor="ECEFF1" if i % 2 == 0 else "FFFFFF")
        ws2.cell(i, 1, elem).fill = fill
        ws2.cell(i, 1).alignment = al_esq
        ws2.cell(i, 1).border = borda
        ws2.cell(i, 2, val).fill = fill
        ws2.cell(i, 2).alignment = al_centro
        ws2.cell(i, 2).border = borda
        ws2.row_dimensions[i].height = 20

    wb.save("checklist_conformidade.xlsx")


def gerar_json(estado):
    """Gera o log estruturado em formato JSON."""
    log = {
        "meta": {
            "sistema": "Inspector BIM — Edificação de Apoio Agricola",
            "versao": "1.0",
            "data": datetime.now().isoformat(),
            "ficheiro_ifc": estado["caminho_ifc"],
            "projecto": estado["elementos_ifc"]["projecto"],
        },
        "elementos_extraidos": estado["elementos_ifc"],
        "verificacao": estado["verificacao"],
        "medicoes": estado["medicoes"],
        "recomendacoes": estado.get("recomendacoes_llm"),
    }
    with open("log_inspector.json", "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ============================================================
# AGENTE 5 — Sintetizador
# ============================================================

def agente_sintetizador(estado: EstadoInspectorAgricola) -> dict:
    """Usa o histórico de mensagens para gerar o relatório final com o LLM."""
    st.write("📄 **[Agente Sintetizador]** A gerar relatório final...")

    dados = estado["elementos_ifc"]
    verificacao = estado["verificacao"]
    medicoes = estado["medicoes"]

    mensagens_para_llm = [
        SystemMessage(content=
            "És um engenheiro técnico especializado em edificações agrícolas em Portugal. "
            "Com base nos relatórios dos agentes abaixo, redige um relatório técnico final "
            "em Português de Portugal. Estrutura o relatório com: "
            "1. Sumário Executivo, "
            "2. Dados do Modelo IFC, "
            "3. Verificação de Conformidade, "
            "4. Medições, "
            "5. Recomendações Técnicas (se aplicável), "
            "6. Conclusão. "
            "Usa linguagem técnica e formal."
        )
    ] + estado["messages"]

    resposta = llm.invoke(mensagens_para_llm)
    relatorio = resposta.content

    with open("relatorio_final.txt", "w", encoding="utf-8") as f:
        f.write(relatorio)

    gerar_docx(relatorio, dados, verificacao)
    gerar_xlsx(verificacao, medicoes, dados)
    gerar_json(estado)

    st.write("   ✅ relatorio_inspector.docx gerado")
    st.write("   ✅ checklist_conformidade.xlsx gerada")
    st.write("   ✅ log_inspector.json gerado")

    return {
        "saidas": {
            "relatorio_txt": "relatorio_final.txt",
            "relatorio_docx": "relatorio_inspector.docx",
            "checklist_xlsx": "checklist_conformidade.xlsx",
            "log_json": "log_inspector.json",
        },
        "messages": [AIMessage(content="[Sintetizador] Relatório técnico final gerado.")]
    }


# ============================================================
# Roteamento Condicional
# ============================================================

def rotear_apos_quantificador(estado: EstadoInspectorAgricola) -> str:
    nao_conformidades = estado["verificacao"]["nao_conformidades"]
    if nao_conformidades:
        return "agente_recomendacoes"
    else:
        return "agente_sintetizador"


# ============================================================
# Construção do Grafo
# ============================================================

def construir_grafo():
    builder = StateGraph(EstadoInspectorAgricola)
    builder.add_node("agente_extrator",     agente_extrator_ifc)
    builder.add_node("agente_verificador",  agente_verificador)
    builder.add_node("agente_quantificador", agente_quantificador)
    builder.add_node("agente_recomendacoes", agente_recomendacoes)
    builder.add_node("agente_sintetizador", agente_sintetizador)

    builder.add_edge(START, "agente_extrator")
    builder.add_edge("agente_extrator",     "agente_verificador")
    builder.add_edge("agente_verificador",  "agente_quantificador")
    builder.add_conditional_edges(
        "agente_quantificador",
        rotear_apos_quantificador,
        {
            "agente_recomendacoes": "agente_recomendacoes",
            "agente_sintetizador":  "agente_sintetizador",
        }
    )
    builder.add_edge("agente_recomendacoes", "agente_sintetizador")
    builder.add_edge("agente_sintetizador",  END)
    return builder.compile()


# ============================================================
# Interface Streamlit
# ============================================================

st.set_page_config(page_title="Inspector BIM", page_icon="🏗️", layout="centered")

st.title("🏗️ Inspector BIM — Edificação de Apoio Agrícola")
st.caption("Master em IA para Arquitectura, Engenharia e Construção — Zigurat Institute of Technology")
st.divider()

# --- Configuração ---
with st.sidebar:
    st.header("⚙️ Configuração")

    # API Key: tenta primeiro os secrets do Streamlit, depois pede ao utilizador
    chave_default = st.secrets.get("ANTHROPIC_API_KEY", "") if hasattr(st, "secrets") else ""
    api_key_input = st.text_input(
        "API Key Anthropic",
        value=chave_default,
        type="password",
        help="Introduz a tua chave Anthropic. Em produção, define-a em st.secrets."
    )

    st.markdown("---")
    st.markdown(
        "**Agentes do pipeline:**\n"
        "1. Extrator IFC\n"
        "2. Verificador\n"
        "3. Quantificador\n"
        "4. Recomendações LLM *(condicional)*\n"
        "5. Sintetizador"
    )

# --- Upload do ficheiro IFC ---
st.subheader("📁 Ficheiro IFC")
ficheiro_ifc = st.file_uploader(
    "Carrega o ficheiro .ifc do modelo BIM",
    type=["ifc"],
    help="Exporta o modelo do Revit ou outro software BIM em formato IFC2X3 ou IFC4."
)

# --- Botão de execução ---
st.divider()
executar = st.button("▶ Executar Análise", type="primary", use_container_width=True)

if executar:
    if not ficheiro_ifc:
        st.error("❌ Por favor carrega um ficheiro IFC antes de executar.")
        st.stop()
    if not api_key_input:
        st.error("❌ Por favor introduz a API Key da Anthropic na barra lateral.")
        st.stop()

    # Inicializar o LLM com a chave fornecida
    os.environ["ANTHROPIC_API_KEY"] = api_key_input
    llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0, max_tokens=1024)

    # Guardar o IFC em ficheiro temporário (IfcOpenShell precisa de um caminho)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
        tmp.write(ficheiro_ifc.read())
        ifc_path = tmp.name

    st.subheader("🔄 Execução do Pipeline")

    with st.spinner("A executar sistema multi-agente..."):
        grafo = construir_grafo()
        resultado = grafo.invoke({
            "messages":        [],
            "caminho_ifc":     ifc_path,
            "elementos_ifc":   None,
            "verificacao":     None,
            "medicoes":        None,
            "recomendacoes_llm": None,
            "saidas":          None,
        })

    st.success("✅ Análise concluída!")
    st.divider()

    # --- Relatório ---
    st.subheader("📋 Relatório Final")
    with open("relatorio_final.txt", encoding="utf-8") as f:
        relatorio_txt = f.read()
    st.text_area("Conteúdo do relatório", relatorio_txt, height=400)

    # --- Downloads ---
    st.subheader("⬇️ Descarregar Ficheiros")
    col1, col2, col3 = st.columns(3)

    with col1:
        with open("relatorio_inspector.docx", "rb") as f:
            st.download_button(
                "📄 Relatório Word",
                f,
                file_name="relatorio_inspector.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
    with col2:
        with open("checklist_conformidade.xlsx", "rb") as f:
            st.download_button(
                "📊 Checklist Excel",
                f,
                file_name="checklist_conformidade.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    with col3:
        with open("log_inspector.json", "rb") as f:
            st.download_button(
                "🗂️ Log JSON",
                f,
                file_name="log_inspector.json",
                mime="application/json",
                use_container_width=True,
            )
