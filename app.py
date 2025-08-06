import streamlit as st
import pandas as pd
from datetime import datetime
import os
import unicodedata
import re

# --- Configuração da Página ---
st.set_page_config(page_title="Atualização de Projetos", page_icon="🔄", layout="wide")

# --- CSS Customizado (Opcional) ---
st.markdown("""
<style>
    .st-emotion-cache-16txtl3 { padding-top: 2rem; }
    .st-form { border: 1px solid #e6e6e6; padding: 1.5rem; border-radius: 0.5rem; }
</style>
""", unsafe_allow_html=True)

# --- Funções Utilitárias (Copiadas do App de Análise) ---
def padronizar_nome(texto):
    if not isinstance(texto, str):
        return texto
    texto = re.sub(r'\s*\([^)]*\)', '', texto)
    texto_normalizado = unicodedata.normalize('NFKD', texto)\
        .encode('ascii', 'ignore')\
        .decode('utf-8')\
        .strip().lower()
    return re.sub(r'\s+', '_', texto_normalizado)

def parse_potencia_numerica(texto_potencia):
    if not isinstance(texto_potencia, str):
        return None
    # Tenta encontrar um número (inteiro ou decimal com ponto ou vírgula)
    match = re.search(r'[\d,.]+', texto_potencia)
    if match:
        try:
            numero_str = match.group(0).replace(',', '.')
            return float(numero_str)
        except (ValueError, TypeError):
            return None
    return None

# --- Carregamento de Dados Técnicos (Copiado do App de Análise) ---
@st.cache_data
def carregar_dados_tecnicos():
    try:
        df_tensao = pd.read_csv("municipios_tensao.csv", sep=r'\s*,\s*', engine='python')
        df_disjuntores = pd.read_csv("tabela_disjuntores.csv", sep=r'\s*,\s*', engine='python')
        df_potencia_max = pd.read_csv("tabela_potencia_maxima.csv", sep=r'\s*,\s*', engine='python')
    except FileNotFoundError as e:
        st.error(f"Erro de carregamento de dados técnicos: O arquivo {e.filename} não foi encontrado. Certifique-se de que os arquivos `municipios_tensao.csv`, `tabela_disjuntores.csv` e `tabela_potencia_maxima.csv` estão na mesma pasta do aplicativo.")
        return None, None, None

    # Padronização de colunas e dados
    for df in [df_tensao, df_disjuntores, df_potencia_max]:
        df.columns = [padronizar_nome(col) for col in df.columns]
    if 'tensao' in df_tensao.columns:
        df_tensao['tensao'] = df_tensao['tensao'].astype(str).str.strip().str.replace('V$', '', regex=True)
    if 'tensao' in df_disjuntores.columns:
        df_disjuntores['tensao'] = df_disjuntores['tensao'].astype(str).str.strip().str.replace('V$', '', regex=True)

    # Parse da carga instalada
    def parse_carga_range(range_str):
        if not isinstance(range_str, str) or range_str.strip() == '-': return 0.0, 0.0
        try:
            range_str = range_str.replace(',', '.').strip()
            parts = [p.strip() for p in range_str.split('-')]
            if len(parts) == 2: return float(parts[0]), float(parts[1])
            elif len(parts) == 1 and parts[0]: val = float(parts[0]); return val, val
            else: return 0.0, 0.0
        except: return 0.0, 0.0

    if 'carga_instalada' in df_disjuntores.columns:
        cargas = df_disjuntores['carga_instalada'].apply(parse_carga_range)
        df_disjuntores[['carga_min_kw', 'carga_max_kw']] = pd.DataFrame(cargas.tolist(), index=df_disjuntores.index)
    else:
        st.error("Erro: Coluna 'Carga Instalada' não encontrada em `tabela_disjuntores.csv`.")
        return None, None, None

    # Merge e preparação final dos dados
    df_dados_tecnicos = pd.merge(df_disjuntores, df_potencia_max, on=['tensao', 'categoria'], how='left')
    df_tensao['municipio'] = df_tensao['municipio'].str.strip().apply(padronizar_nome)
    coluna_pot = [col for col in df_dados_tecnicos.columns if 'potencia_maxima' in col]
    if coluna_pot:
        df_dados_tecnicos.rename(columns={coluna_pot[0]: 'potencia_maxima_geracao_str'}, inplace=True)
        df_dados_tecnicos['limite_numerico_busca'] = df_dados_tecnicos['potencia_maxima_geracao_str'].apply(parse_potencia_numerica)
    else:
        st.error("Erro: Coluna de potência máxima não encontrada em `tabela_potencia_maxima.csv`.")
        return None, None, None

    mapa_ligacao = {
        "Monofásico": ["M0", "M1", "M2", "M3"],
        "Bifásico": ["B0", "B1", "B2"],
        "Trifásico": [f"T{i}" for i in range(13)]
    }
    return df_tensao, df_dados_tecnicos, mapa_ligacao

# --- Função para Gerar a Observação ---
def gerar_observacao_analise(cidade, tipo_ligacao, carga_instalada, potencia_kit_kwp, df_tensao, df_dados_tecnicos, mapa_ligacao):
    # Validações iniciais
    if not cidade: return "ERRO: Cidade não informada."
    if not tipo_ligacao: return "ERRO: Fase da ligação não informada."
    if potencia_kit_kwp is None or potencia_kit_kwp <= 0: return "Potência do kit atual não informada ou inválida para análise."

    # Encontrar tensão da cidade
    cidade_norm = padronizar_nome(cidade)
    tensao_info = df_tensao.loc[df_tensao["municipio"] == cidade_norm, "tensao"]
    if tensao_info.empty: return f"ERRO: Tensão para a cidade '{cidade}' não encontrada."
    tensao = tensao_info.values[0]

    # Encontrar faixa atual
    categorias_permitidas = mapa_ligacao.get(tipo_ligacao, [])
    df_faixa_encontrada = df_dados_tecnicos[
        (df_dados_tecnicos["tensao"] == tensao) &
        (df_dados_tecnicos["categoria"].isin(categorias_permitidas)) &
        (carga_instalada >= df_dados_tecnicos["carga_min_kw"]) &
        (carga_instalada <= df_dados_tecnicos["carga_max_kw"])
    ]

    if df_faixa_encontrada.empty: return f"ERRO: Nenhuma faixa encontrada para Carga de {carga_instalada} kW, Ligação {tipo_ligacao} e Tensão {tensao}."

    resultado_atual = df_faixa_encontrada.iloc[0]
    faixa_atual = resultado_atual["categoria"]
    limite_atual = resultado_atual["limite_numerico_busca"]

    # Validação
    if limite_atual is None or potencia_kit_kwp <= limite_atual:
        return f"APROVADO: O kit de {potencia_kit_kwp:.2f} kWp é compatível com a categoria atual ({faixa_atual}), que permite até {resultado_atual['potencia_maxima_geracao_str']}."

    # Se reprovado, buscar solução
    observacao = f"REPROVADO: O kit de {potencia_kit_kwp:.2f} kWp excede o limite de {resultado_atual['potencia_maxima_geracao_str']} para a categoria atual ({faixa_atual}).\n\n"

    # Buscar solução em ligações (da atual em diante)
    tipos_de_busca = []
    if tipo_ligacao == "Monofásico": tipos_de_busca = ["Monofásico", "Bifásico", "Trifásico"]
    elif tipo_ligacao == "Bifásico": tipos_de_busca = ["Bifásico", "Trifásico"]
    else: tipos_de_busca = ["Trifásico"]

    solucao_encontrada = False
    for tipo_busca in tipos_de_busca:
        categorias_busca = mapa_ligacao.get(tipo_busca, [])
        df_solucao = df_dados_tecnicos[
            (df_dados_tecnicos["tensao"] == tensao) &
            (df_dados_tecnicos["categoria"].isin(categorias_busca)) &
            (df_dados_tecnicos["limite_numerico_busca"] >= potencia_kit_kwp)
        ].sort_values(by="carga_min_kw")

        if not df_solucao.empty:
            solucao = df_solucao.iloc[0]
            solucao_potencia_max_str = solucao.get('potencia_maxima_geracao_str', 'N/A')
            
            titulo_solucao = "Solução Sugerida:"
            if tipo_busca != tipo_ligacao:
                titulo_solucao = f"Solução Sugerida (com upgrade para {tipo_busca}):"

            observacao += (
                f"{titulo_solucao}\n"
                f"Para aprovar um kit de {potencia_kit_kwp:.2f} kWp, a unidade precisa ser reclassificada, atendendo aos seguintes requisitos:\n"
                f"- **Alteração Necessária:** Solicitar à concessionária a alteração para **Ligação {tipo_busca}** (se diferente da atual).\n"
                f"- **Nova Categoria:** `{solucao['categoria']}`\n"
                f"- **Carga Instalada Necessária:** Entre {solucao['carga_min_kw']:.2f} kW e {solucao['carga_max_kw']:.2f} kW.\n"
                f"- **Novo Limite de Geração:** Com esta categoria, o limite de potência do kit será de **{solucao_potencia_max_str}**."
            )
            solucao_encontrada = True
            break
    
    if not solucao_encontrada:
        observacao += f"Não foi encontrada nenhuma categoria (nem em ligações superiores) que suporte os {potencia_kit_kwp:.2f} kWp desejados para a tensão {tensao}."

    return observacao


# --- Função para salvar dados no CSV ---
def salvar_dados_csv(dados, nome_arquivo="atualizacoes_projetos.csv"):
    if os.path.exists(nome_arquivo):
        df_existente = pd.read_csv(nome_arquivo)
        df_atualizado = pd.concat([df_existente, dados], ignore_index=True)
    else:
        df_atualizado = dados
    df_atualizado.to_csv(nome_arquivo, index=False)
    st.success("✅ Atualização salva com sucesso!")


# --- Início da Interface do App ---
st.title("🔄 Atualização de Projeto - 77 COS")
st.markdown("Preencha as informações abaixo para registrar uma atualização de projeto.")

# Carregar dados técnicos
df_tensao, df_dados_tecnicos, mapa_ligacao = carregar_dados_tecnicos()

# Inicializar session state para observação
if 'observacao_gerada' not in st.session_state:
    st.session_state.observacao_gerada = ""

# --- Formulário de Entrada ---
if df_dados_tecnicos is not None: # Só mostra o formulário se os dados técnicos foram carregados
    with st.form("form_atualizacao"):
        
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🧾 Dados do Cliente")
            cliente = st.text_input("Nome do Cliente")
            cidade = st.text_input("Cidade")
            carga_instalada = st.number_input("Carga Instalada (kW)", min_value=0.0, step=0.1, format="%.1f")

        with c2:
            st.subheader("🗓️ Datas e Fases")
            data_envio = st.date_input("Data do Envio", value=datetime.today())
            fase = st.selectbox("Fase da ligação", ["Monofásico", "Bifásico", "Trifásico"])
            comentario_notion = st.text_area("Comentário do Notion")

        st.divider()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader("🔌 Kit Instalado")
            kit_inst_pot = st.text_input("Potência (kWp)", key="kit_inst_pot")
            kit_inst_placa = st.text_input("Placas", key="kit_inst_placa")
            kit_inst_inversor = st.text_input("Inversor", key="kit_inst_inversor")
        with col2:
            st.subheader("📦 Kit Enviado")
            kit_env_pot = st.text_input("Potência (kWp)", key="kit_env_pot")
            kit_env_placa = st.text_input("Placas", key="kit_env_placa")
            kit_env_inversor = st.text_input("Inversor", key="kit_env_inversor")
        with col3:
            st.subheader("⚡ Kit Atual Instalado")
            kit_atual_pot = st.text_input("Potência (kWp)", key="kit_atual_pot")
            kit_atual_placa = st.text_input("Placas", key="kit_atual_placa")
            kit_atual_inversor = st.text_input("Inversor", key="kit_atual_inversor")

        st.divider()

        # --- NOVA SEÇÃO DE ANÁLISE ---
        st.subheader("🔎 Análise de Viabilidade e Geração de Observação")
        st.info("Preencha os campos `Cidade`, `Fase`, `Carga Instalada` e `Kit Atual - Potência` e clique no botão abaixo para gerar a observação técnica automaticamente.")

        # Botão de análise que atualiza o session state
        if st.form_submit_button("🔍 Analisar Kit e Gerar Observação"):
            potencia_para_analise = parse_potencia_numerica(kit_atual_pot)
            st.session_state.observacao_gerada = gerar_observacao_analise(
                cidade, fase, carga_instalada, potencia_para_analise,
                df_tensao, df_dados_tecnicos, mapa_ligacao
            )
            st.rerun() # Força o recarregamento para exibir o texto na área de observação

        # Área de texto que usa o valor do session state
        observacao = st.text_area(
            "📝 Observação (Gerada automaticamente ou preenchida manualmente)",
            value=st.session_state.observacao_gerada,
            height=200
        )

        st.divider()

        # Botão final para salvar tudo
        if st.form_submit_button("✅ Salvar Atualização no Histórico"):
            nova_linha = pd.DataFrame([{
                "Cliente": cliente, "Data de Envio": data_envio, "Cidade": cidade,
                "Fase": fase, "Carga Instalada": carga_instalada,
                "Kit Instalado - Potência": kit_inst_pot, "Kit Instalado - Placas": kit_inst_placa, "Kit Instalado - Inversor": kit_inst_inversor,
                "Kit Enviado - Potência": kit_env_pot, "Kit Enviado - Placas": kit_env_placa, "Kit Enviado - Inversor": kit_env_inversor,
                "Comentário do Notion": comentario_notion,
                "Kit Atual - Potência": kit_atual_pot, "Kit Atual - Placas": kit_atual_placa, "Kit Atual - Inversor": kit_atual_inversor,
                "Observação": observacao, # Salva o valor final da área de texto
            }])
            salvar_dados_csv(nova_linha)
            # Limpa o estado da sessão para a próxima entrada
            st.session_state.observacao_gerada = ""


# --- Visualização dos dados já salvos ---
if os.path.exists("atualizacoes_projetos.csv"):
    st.divider()
    st.subheader("📋 Histórico de Atualizações")
    df = pd.read_csv("atualizacoes_projetos.csv")
    st.dataframe(df)

st.caption("Desenvolvido por Vitória de Sales Sena ⚡")

