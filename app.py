import streamlit as st
import pandas as pd
import re
import unicodedata

# --- Configuração da Página ---
st.set_page_config(page_title="Análise de Atualização de Projetos", page_icon="⚙️", layout="centered")

# --- Funções Utilitárias ---

def padronizar_nome(texto):
    """Normaliza o nome da cidade para busca no CSV."""
    if not isinstance(texto, str): return texto
    texto = re.sub(r'\s*\([^)]*\)', '', texto)
    texto_normalizado = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8').strip().lower()
    return re.sub(r'\s+', '_', texto_normalizado)

def parse_potencia_numerica(texto_potencia):
    """Extrai um número de uma string, mesmo com 'kWp' ou vírgulas."""
    if not isinstance(texto_potencia, str): return None
    match = re.search(r'[\d,.]+', texto_potencia)
    if match:
        try:
            return float(match.group(0).replace(',', '.'))
        except (ValueError, TypeError):
            return None
    return None

# --- NOVA FUNÇÃO DE ANÁLISE COM SAÍDA SIMPLIFICADA ---
def gerar_instrucao_tecnica(cidade, tipo_ligacao, carga_instalada, potencia_kit_kwp, df_tensao, df_dados_tecnicos, mapa_ligacao):
    """
    Analisa os dados e retorna uma instrução simples e direta.
    """
    # Validações iniciais
    if not all([cidade, tipo_ligacao, potencia_kit_kwp]):
        return "ERRO: Preencha todos os campos necessários para a análise (Cidade, Fase, Carga e Potência do Kit)."

    # Encontrar tensão e faixa atual
    cidade_norm = padronizar_nome(cidade)
    tensao_info = df_tensao.loc[df_tensao["municipio"] == cidade_norm, "tensao"]
    if tensao_info.empty: return f"ERRO: Tensão para a cidade '{cidade}' não encontrada."
    tensao = tensao_info.values[0]

    categorias_permitidas = mapa_ligacao.get(tipo_ligacao, [])
    df_faixa_encontrada = df_dados_tecnicos[
        (df_dados_tecnicos["tensao"] == tensao) &
        (df_dados_tecnicos["categoria"].isin(categorias_permitidas)) &
        (carga_instalada >= df_dados_tecnicos["carga_min_kw"]) &
        (carga_instalada <= df_dados_tecnicos["carga_max_kw"])
    ]

    if df_faixa_encontrada.empty: return f"ERRO: Nenhuma faixa encontrada para os dados atuais (Carga: {carga_instalada}kW, Ligação: {tipo_ligacao})."

    resultado_atual = df_faixa_encontrada.iloc[0]
    limite_atual = resultado_atual["limite_numerico_busca"]

    # Cenário 1: Projeto está conforme
    if limite_atual is None or potencia_kit_kwp <= limite_atual:
        return "O projeto pode ser atualizado. O cliente ainda se mantém dentro da faixa."

    # Cenário 2: Projeto precisa de readequação
    # Se reprovado, buscar solução
    tipos_de_busca = ["Monofásico", "Bifásico", "Trifásico"]
    try:
        indice_inicio_busca = tipos_de_busca.index(tipo_ligacao)
    except ValueError:
        return f"ERRO: Tipo de ligação '{tipo_ligacao}' inválido."

    for tipo_busca in tipos_de_busca[indice_inicio_busca:]:
        categorias_busca = mapa_ligacao.get(tipo_busca, [])
        df_solucao = df_dados_tecnicos[
            (df_dados_tecnicos["tensao"] == tensao) &
            (df_dados_tecnicos["categoria"].isin(categorias_busca)) &
            (df_dados_tecnicos["limite_numerico_busca"] >= potencia_kit_kwp)
        ].sort_values(by="carga_min_kw")

        if not df_solucao.empty:
            solucao = df_solucao.iloc[0]
            nova_faixa = solucao['categoria']
            nova_carga_min_w = int(solucao['carga_min_kw'] * 1000)
            
            # Monta a mensagem de alteração
            partes_alteracao = []
            if tipo_busca != tipo_ligacao:
                partes_alteracao.append(f"MUDAR LIGAÇÃO PARA {tipo_busca.upper()}")
            
            partes_alteracao.append(f"MUDAR PARA FAIXA {nova_faixa}")
            partes_alteracao.append(f"AUMENTAR CARGA PARA NO MÍNIMO {nova_carga_min_w} W")
            
            alteracao_necessaria = " e ".join(partes_alteracao)
            
            return f"O cliente não está mais dentro da faixa. Alteração necessária: {alteracao_necessaria}."
            
    return f"NÃO FOI ENCONTRADA SOLUÇÃO para um kit de {potencia_kit_kwp} kWp com a tensão de {tensao}."


# --- Carregamento de Dados ---
@st.cache_data
def carregar_dados_tecnicos():
    try:
        df_tensao = pd.read_csv("municipios_tensao.csv", sep=r'\s*,\s*', engine='python')
        df_disjuntores = pd.read_csv("tabela_disjuntores.csv", sep=r'\s*,\s*', engine='python')
        df_potencia_max = pd.read_csv("tabela_potencia_maxima.csv", sep=r'\s*,\s*', engine='python')
    except FileNotFoundError as e:
        st.error(f"Erro: O arquivo `{e.filename}` não foi encontrado. Certifique-se de que os 3 arquivos .csv estão na mesma pasta do aplicativo.")
        return None, None, None

    for df in [df_tensao, df_disjuntores, df_potencia_max]:
        df.columns = [padronizar_nome(col) for col in df.columns]
    if 'tensao' in df_tensao.columns: df_tensao['tensao'] = df_tensao['tensao'].astype(str).str.strip().str.replace('V$', '', regex=True)
    if 'tensao' in df_disjuntores.columns: df_disjuntores['tensao'] = df_disjuntores['tensao'].astype(str).str.strip().str.replace('V$', '', regex=True)

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
        st.error("Erro: Coluna 'carga_instalada' não encontrada em `tabela_disjuntores.csv`.")
        return None, None, None

    df_dados_tecnicos = pd.merge(df_disjuntores, df_potencia_max, on=['tensao', 'categoria'], how='left')
    coluna_pot = [col for col in df_dados_tecnicos.columns if 'potencia_maxima' in col]
    if coluna_pot:
        df_dados_tecnicos.rename(columns={coluna_pot[0]: 'potencia_maxima_geracao_str'}, inplace=True)
        df_dados_tecnicos['limite_numerico_busca'] = df_dados_tecnicos['potencia_maxima_geracao_str'].apply(lambda x: float(str(x).replace(',','.')) if isinstance(x, str) and re.search(r'\d', x) else None)
    else:
        st.error("Erro: Coluna de potência máxima não encontrada em `tabela_potencia_maxima.csv`.")
        return None, None, None

    mapa_ligacao = {"Monofásico": ["M0", "M1", "M2", "M3"], "Bifásico": ["B0", "B1", "B2"], "Trifásico": [f"T{i}" for i in range(13)]}
    return df_tensao, df_dados_tecnicos, mapa_ligacao

# --- Interface Principal do App ---
st.title("⚙️ Analisador de Atualização de Projetos")
st.markdown("Preencha os dados do projeto abaixo para receber a instrução de atualização.")

# Carregar dados
df_tensao, df_dados_tecnicos, mapa_ligacao = carregar_dados_tecnicos()

if df_dados_tecnicos is not None:
    with st.form("form_analise"):
        st.subheader("Dados do Projeto")
        
        cidade = st.text_input("Cidade")
        fase = st.selectbox("Fase da ligação", ["Monofásico", "Bifásico", "Trifásico"])
        carga_instalada_kw = st.number_input("Carga Instalada (kW)", min_value=0.0, step=0.1, format="%.2f")
        potencia_kit_str = st.text_input("Potência do Kit ATUAL (kWp)")
        
        submitted = st.form_submit_button("Analisar e Gerar Instrução", use_container_width=True, type="primary")

        if submitted:
            potencia_kit_kwp = parse_potencia_numerica(potencia_kit_str)
            
            with st.spinner("Analisando..."):
                instrucao = gerar_instrucao_tecnica(
                    cidade, fase, carga_instalada_kw, potencia_kit_kwp,
                    df_tensao, df_dados_tecnicos, mapa_ligacao
                )
                
                # Exibe o resultado de forma condicional
                if "ERRO" in instrucao or "NÃO FOI ENCONTRADA" in instrucao:
                    st.error(instrucao)
                elif "não está mais dentro da faixa" in instrucao:
                    st.warning(instrucao)
                else:
                    st.success(instrucao)
else:
    st.warning("Aguardando o carregamento dos arquivos de dados técnicos...")

st.caption("Desenvolvido por Vitória de Sales Sena ⚡")
