# Inspector BIM — Edificação de Apoio Agrícola

**Master em IA para Arquitectura, Engenharia e Construção — Zigurat Institute of Technology**

Módulo 5 — Tema 2: Agentic IA | Tarefa Individual | Daniel Veludo

---

## Objectivo

Sistema multi-agente em LangGraph que lê um modelo IFC de uma edificação agrícola e verifica automaticamente a sua conformidade com a legislação portuguesa aplicável, produzindo documentação técnica estruturada.

O caso de estudo é a Casa de Máquinas da Quinta do Panascal (Valença do Douro), exportada do Autodesk Revit 2026 em formato IFC2X3.

O sistema executa cinco agentes em sequência:

1. Agente Extrator — lê o ficheiro IFC com IfcOpenShell e extrai paredes, janelas, portas, lajes e espaços funcionais
2. Agente Verificador — aplica critérios de conformidade com base em legislação portuguesa (DL 163/2006, DL 173/2005, DL 347/93, Portaria 702/80)
3. Agente Quantificador — calcula medições de todos os elementos construtivos
4. Agente Recomendações (condicional) — invoca o Claude para gerar recomendações técnicas, apenas se existirem não conformidades
5. Agente Sintetizador — usa o histórico de mensagens para gerar o relatório final via LLM e produz os três entregáveis

Os entregáveis produzidos são um relatório Word (.docx), uma checklist Excel (.xlsx) e um log estruturado (.json).

---

## Dependências

```
langgraph
langchain
langchain-anthropic
anthropic
ifcopenshell
openpyxl
python-docx
pandas
```

Instalação (Google Colab ou ambiente local):

```bash
pip install langgraph langchain langchain-anthropic anthropic ifcopenshell pandas openpyxl python-docx
```

É necessária uma API Key da Anthropic para o Agente de Recomendações e o Agente Sintetizador invocarem o Claude. Os restantes agentes funcionam sem API Key.

---

## Como Executar

### Google Colab (recomendado)

1. Abrir o Google Colab em colab.research.google.com
2. Carregar o ficheiro `M5T2_Tarefa_Daniel_Veludo.ipynb` via `Ficheiro > Carregar notebook`
3. No painel lateral, ir ao separador `Secrets` (ícone de cadeado) e adicionar um secret com o nome `ANTHROPIC_API_KEY` e o valor da chave Anthropic
4. Carregar o ficheiro `edificio_agricola_com_erro.ifc` para o ambiente Colab (arrastar para o painel de ficheiros ou usar `Ficheiro > Carregar`)
5. Confirmar que o nome do ficheiro na célula de configuração (`IFC_PATH`) corresponde ao nome do ficheiro carregado
6. Executar todas as células por ordem: `Ambiente de execução > Executar tudo`

Após a execução, a última célula faz o download automático dos três ficheiros gerados.

### Ambiente Local

```bash
# 1. Instalar dependências
pip install langgraph langchain langchain-anthropic anthropic ifcopenshell pandas openpyxl python-docx

# 2. Definir a API Key
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Abrir o notebook
jupyter notebook M5T2_Tarefa_Daniel_Veludo.ipynb
```

Na célula de configuração da API Key, substituir o bloco `from google.colab import userdata` por:

```python
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."
```

---

## Ficheiro IFC

O ficheiro `edificio_agricola_com_erro.ifc` corresponde à Casa de Máquinas da Quinta do Panascal, exportado do Autodesk Revit 2026 no esquema IFC2X3 (CoordinationView V2.0). O modelo inclui paredes, janelas, portas (uma delas não cumpre, propositadamente, a largura mínima de vão livre exigida por lei), lajes, pilares, vigas e espaços funcionais do edifício de apoio agrícola.

---

## Estrutura do Repositório

```
inspector-bim-agricola/
├── M5T2_Tarefa_Daniel_Veludo.ipynb   <- notebook principal
├── README.md                         <- este ficheiro
└── edificio_agricola_com_erro.ifc    <- modelo IFC de input
```

---

*Master em IA para Arquitectura, Engenharia e Construção — Zigurat Institute of Technology*
